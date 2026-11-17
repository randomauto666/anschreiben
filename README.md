# Anschreiben-Generator

Lebenslauf (PDF/DOCX/TXT) hochladen, Unternehmen eintragen – eine KI schreibt ein passendes Bewerbungsanschreiben (DIN-5008-Blatt, bearbeitbar, PDF über Druckdialog).

## Start
```
AI_BASE_URL=https://api.groq.com/openai/v1 AI_API_KEY=... AI_MODEL=llama-3.3-70b-versatile python3 server.py
```
Läuft auf `127.0.0.1:8792` (`PORT` änderbar), nur Python-Standardbibliothek. Jede OpenAI-kompatible API funktioniert.
`anschreiben.service` = systemd-Vorlage (Konfig in `/etc/anschreiben.env`).

Der Lebenslauf wird im Browser zu Text umgewandelt, der Server speichert nichts. Limit: 8 Anfragen pro IP und Stunde.
