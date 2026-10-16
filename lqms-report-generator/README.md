# LQMS Report Generator

Auswertungs-Software zum **LQMS** (Luftqualitätsmesssystem) aus dem Make-Artikel
„Unsichtbare Gefahr – ein tragbares Luftqualitätsmessgerät selbst bauen".

Das Gerät protokolliert im Sekundentakt Luftqualitätsdaten (Feinstaub PM1–PM10,
VOC, NOx, Temperatur, Feuchte, Lautstärke) auf eine MicroSD-Karte. Dieses
Programm liest die `data.csv` von der Karte und erzeugt daraus automatisch einen
**Luftqualitätsbericht als PDF** – mit Gesamtauswertung, Detailseiten pro
Tätigkeit und einer Lärm-Auswertung (dB).

## Voraussetzungen

- Python 3.10+ (getestet unter Windows 11)
- Pakete aus `requirements.txt`:

```
pip install -r requirements.txt
```

`tkinter` gehört zur Standardbibliothek; unter Linux ggf. `sudo apt install python3-tk`.

## Aus dem Quellcode ausführen

Die `data.csv` muss neben dem Skript liegen (Ordner `data/`):

```
cd data
python generate_report.py
```

Die erzeugten Diagramme landen in `data/pictures/`, der fertige PDF-Bericht
wird gespeichert und geöffnet.

## Als EXE bauen (für die MicroSD-Karte)

Auf der Karte startet die Datei **„Report erstellen.bat"** die kompilierte
`generate_report.exe`. Diese lässt sich mit PyInstaller erzeugen:

```
cd data
pyinstaller generate_report.spec
```

Danach liegt die EXE unter `data/dist/generate_report.exe`. Layout auf der Karte:

```
MicroSD/
├── Report erstellen.bat
└── data/
    ├── data.csv
    ├── dist/generate_report.exe
    └── pictures/
```

## Datenformat (`data.csv`)

Spalten: `Zeit, Seriennummer, DeviceStatus, Kritisch, Aktivitaet, AkkuVolt,
AkkuProzent, PM1.0, PM2.5, PM4.0, PM10.0, VOC, NOx, Temperatur, Feuchte,
Lautstaerke_dB`. Die mitgelieferte `data.csv` ist ein anonymisierter
Beispieldatensatz.

## Ordnerstruktur

```
lqms-report-generator/
├── README.md
├── requirements.txt
├── Report erstellen.bat
├── Dokumentation_Python_Code.xlsx
└── data/
    ├── generate_report.py      # Haupt-Report-Generator (PDF)
    ├── analyse_data.py         # ergänzende Akku-/Statusauswertung
    ├── generate_report.spec    # PyInstaller-Build
    ├── data.csv                # Beispieldaten (anonymisiert)
    └── pictures/               # generierte Diagramme (optional: logo.png)
```

## Hinweise

- Firmenspezifische Inhalte (Logo, Produktlinks) wurden entfernt. Wer ein
  eigenes Logo im Bericht möchte, legt es als `data/pictures/logo.png` ab.
- Das LQMS ist ein Sensibilisierungswerkzeug, **kein geeichtes Messgerät** und
  ersetzt keine arbeitshygienische Messung oder vorgeschriebene PSA.


## Autoren

Ramon Hofer Kraner, Martin Hanselmann
