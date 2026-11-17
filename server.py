#!/usr/bin/env python3
"""Anschreiben-Generator – kleiner HTTP-Dienst (nur Python-Standardbibliothek).

Liefert die statische Seite aus ./public und erzeugt per KI ein Anschreiben.
Der Lebenslauf wird im Browser zu Text umgewandelt und nur für die eine Anfrage
an die KI geschickt – auf dem Server wird nichts gespeichert.

KI = beliebige OpenAI-kompatible Chat-API (Groq, Gemini, OpenRouter, Ollama …).
Konfiguration per Umgebung (systemd EnvironmentFile):
  AI_BASE_URL   z. B. https://api.groq.com/openai/v1
  AI_API_KEY    Schlüssel (leer bei Ollama)
  AI_MODEL      z. B. llama-3.3-70b-versatile
  PORT          Standard 8792
"""
import json
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "public"
PORT = int(os.environ.get("PORT", "8792"))
AI_BASE_URL = os.environ.get("AI_BASE_URL", "").rstrip("/")
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_MODEL = os.environ.get("AI_MODEL", "")

MAX_BODY = 200_000          # Byte pro Anfrage
MAX_CV = 30_000             # Zeichen Lebenslauf
PER_IP = 8                  # Anschreiben pro IP …
WINDOW = 3600               # … pro Stunde
_hits: dict[str, list[float]] = {}

TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon"}

FIELDS = {  # Feld → (Pflicht, Max-Länge)
    "firma": (True, 120), "ansprechpartner": (True, 120), "strasse": (True, 120),
    "hausnummer": (True, 12), "plz": (True, 10), "ort": (True, 80),
    "stelle": (False, 150), "ausschreibung": (False, 6000), "hinweise": (False, 1000),
    "ton": (False, 20),
}

SYSTEM = """Du schreibst professionelle deutsche Bewerbungsanschreiben.
Regeln:
- Nutze ausschließlich Fakten aus dem Lebenslauf. Erfinde keine Abschlüsse, Firmen, Zahlen oder Fähigkeiten.
- Bezug auf das Unternehmen und – falls angegeben – die Stelle und die Ausschreibung.
- Anrede mit dem angegebenen Ansprechpartner (z. B. „Sehr geehrte Frau Müller,“ / „Sehr geehrter Herr Müller,“). Ist das Geschlecht nicht erkennbar: „Guten Tag <Vorname Nachname>,“.
- Aufbau: Einleitung mit Motivation, 1–2 Absätze passende Erfahrung/Stärken mit konkreten Beispielen aus dem Lebenslauf, Schluss mit Gesprächswunsch (und ggf. Eintrittstermin/Gehalt nur wenn in den Hinweisen genannt).
- Länge: maximal eine DIN-A4-Seite Fließtext (ca. 250–380 Wörter). Keine Floskelketten, kein „hiermit bewerbe ich mich“.
- Antworte NUR mit JSON, ohne Markdown, in genau diesem Format:
{"absender":{"name":"","strasse":"","plz_ort":"","telefon":"","email":""},"betreff":"","anrede":"","text":"","gruss":"Mit freundlichen Grüßen"}
- absender: aus dem Lebenslauf; fehlende Angaben als leerer String.
- text: nur die Absätze zwischen Anrede und Grußformel, Absätze mit Leerzeile getrennt."""

TONE = {"modern": "Ton: modern, direkt, freundlich.",
        "klassisch": "Ton: klassisch-förmlich, seriös.",
        "kreativ": "Ton: persönlich und etwas kreativer, aber professionell."}


def limited(ip: str) -> bool:
    now = time.time()
    lst = [t for t in _hits.get(ip, []) if now - t < WINDOW]
    if len(lst) >= PER_IP:
        _hits[ip] = lst
        return True
    lst.append(now)
    _hits[ip] = lst
    if len(_hits) > 5000:  # Speicher klein halten
        for k in list(_hits)[:2500]:
            _hits.pop(k, None)
    return False


def ask_ai(d: dict) -> dict:
    firma = f"""Unternehmen: {d['firma']}
Ansprechpartner: {d['ansprechpartner']}
Anschrift: {d['strasse']} {d['hausnummer']}, {d['plz']} {d['ort']}"""
    if d.get("stelle"):
        firma += f"\nStelle: {d['stelle']}"
    if d.get("ausschreibung"):
        firma += f"\nStellenausschreibung:\n{d['ausschreibung']}"
    if d.get("hinweise"):
        firma += f"\nZusätzliche Hinweise des Bewerbers:\n{d['hinweise']}"
    user = f"{TONE.get(d.get('ton') or 'modern', TONE['modern'])}\n\n{firma}\n\nLebenslauf:\n{d['lebenslauf']}"

    body = {"model": AI_MODEL, "temperature": 0.6, "max_tokens": 1800,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"}}
    req = urllib.request.Request(AI_BASE_URL + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {AI_API_KEY}"} if AI_API_KEY else {})})
    with urllib.request.urlopen(req, timeout=90) as r:
        out = json.loads(r.read())
    txt = out["choices"][0]["message"]["content"].strip()
    if txt.startswith("```"):
        txt = txt.strip("`").removeprefix("json").strip()
    res = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
    if not isinstance(res.get("text"), str) or len(res["text"]) < 100:
        raise ValueError("leere Antwort")
    return res


class H(BaseHTTPRequestHandler):
    server_version = "anschreiben"
    sys_version = ""

    def log_message(self, fmt, *args):  # keine Inhalte loggen, nur Status
        pass

    def ip(self):
        return self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.client_address[0]

    def send(self, code, data, ctype="application/json; charset=utf-8"):
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if ctype.startswith("application/json") else "public, max-age=300")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/status":
            return self.send(200, {"ki": bool(AI_BASE_URL and AI_MODEL)})
        if path in ("", "/"):
            path = "/index.html"
        f = (ROOT / path.lstrip("/")).resolve()
        if ROOT not in f.parents or not f.is_file():
            return self.send(404, b"Nicht gefunden", "text/plain; charset=utf-8")
        self.send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))

    def do_POST(self):
        if self.path != "/api/anschreiben":
            return self.send(404, {"fehler": "Nicht gefunden"})
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self.send(413, {"fehler": "Anfrage zu groß."})
        try:
            d = json.loads(self.rfile.read(n))
        except Exception:
            return self.send(400, {"fehler": "Ungültige Anfrage."})
        clean = {}
        for k, (req, mx) in FIELDS.items():
            v = str(d.get(k) or "").strip()[:mx]
            if req and not v:
                return self.send(400, {"fehler": f"Feld „{k}“ fehlt."})
            clean[k] = v
        cv = str(d.get("lebenslauf") or "").strip()
        if len(cv) < 80:
            return self.send(400, {"fehler": "Lebenslauf enthält zu wenig Text. Bitte PDF/DOCX mit Text (kein Scan) hochladen."})
        clean["lebenslauf"] = cv[:MAX_CV]
        if not (AI_BASE_URL and AI_MODEL):
            return self.send(503, {"fehler": "KI ist noch nicht eingerichtet."})
        if limited(self.ip()):
            return self.send(429, {"fehler": "Zu viele Anfragen. Bitte in einer Stunde erneut versuchen."})
        try:
            return self.send(200, ask_ai(clean))
        except urllib.error.HTTPError as e:
            code = e.code
            print("KI-HTTP-Fehler", code, flush=True)
            return self.send(502, {"fehler": "KI ist gerade ausgelastet. Bitte gleich nochmal versuchen." if code == 429 else "KI-Dienst nicht erreichbar."})
        except Exception as e:
            print("KI-Fehler", type(e).__name__, flush=True)
            return self.send(502, {"fehler": "Anschreiben konnte nicht erzeugt werden. Bitte nochmal versuchen."})


if __name__ == "__main__":
    print(f"anschreiben läuft auf 127.0.0.1:{PORT}, KI {'an' if AI_MODEL else 'AUS'}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
