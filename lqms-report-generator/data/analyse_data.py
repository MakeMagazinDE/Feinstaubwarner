import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
import os
# ==== Ordnerstruktur ====
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = BASE_DIR  # script is now inside 'data'

# Bilder-Verzeichnis anlegen
PICTURE_DIR = os.path.join(DATA_DIR, "pictures")
os.makedirs(PICTURE_DIR, exist_ok=True)

CSV_PATH = os.path.join(BASE_DIR, "data.csv")  # Passe ggf. an
import io
from fpdf import FPDF

import tkinter as tk
from tkinter import messagebox
import subprocess


# ==== CSV einlesen ====
with open(CSV_PATH, 'rb') as f:
    lines = []
    for raw_line in f:
        try:
            line = raw_line.decode('utf-8').strip()
            lines.append(line)
        except UnicodeDecodeError:
            continue

expected_fields = 16
valid_lines = []
for line in lines:
    if not line.strip():
        continue
    fields = line.split(',')
    if "Zeit" in line:
        valid_lines.insert(0, line + '\n')
        continue
    if len(fields) != expected_fields:
        continue
    try:
        datetime.strptime(fields[0].strip(), "%Y-%m-%dT%H:%M:%S")
        valid_lines.append(line + '\n')
    except ValueError:
        continue

df = pd.read_csv(io.StringIO(''.join(valid_lines)), delimiter=",")
df = df.applymap(lambda x: x.replace('\u202f', ' ') if isinstance(x, str) else x)

# ==== Umbenennen & Konvertieren ====
df.rename(columns={
    "Zeit": "timestamp",
    "AkkuVolt": "Battery_Volt",
    "AkkuProzent": "Battery_Pct"
}, inplace=True)

df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df = df.dropna(subset=["timestamp"])

df["date"] = df["timestamp"].dt.date

# ==== Batterieanalyse ====
min_v = df["Battery_Volt"].min()
max_v = df["Battery_Volt"].max()
min_v_pct = df.loc[df["Battery_Volt"] == min_v, "Battery_Pct"].values[0]
max_v_pct = df.loc[df["Battery_Volt"] == max_v, "Battery_Pct"].values[0]

#

# ==== Plot: Akku ====
daily_plot_paths = []
for date, df_day in df.groupby("date"):
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax1.plot(df_day["timestamp"], df_day["Battery_Pct"], label="Akku [%]", color="tab:blue")
    ax1.set_xlabel("Zeit")
    ax1.set_ylabel("Akku [%]", color="tab:blue")
    ax1.set_ylim(0, 100)
    ax1.tick_params(axis='y', labelcolor="tab:blue")

    ax2 = ax1.twinx()
    ax2.plot(df_day["timestamp"], df_day["Battery_Volt"], label="Spannung [V]", color="tab:red")
    ax2.set_ylabel("Spannung [V] (gemessen über Spannungsteiler 150k/100k)", color="tab:red")
    ax2.set_ylim(0, 3)
    ax2.tick_params(axis='y', labelcolor="tab:red")

    fig.tight_layout()
    if str(date) == "2025-05-27":
        plt.title("Batterie- und Spannungsverlauf am 2025-05-27 (Akku war zu Beginn vollständig geladen)")
    elif str(date) == "2025-05-28":
        plt.title("Batterie- und Spannungsverlauf am 2025-05-28 (Akku wurde vollständig entladen)")
    plot_path = os.path.join(PICTURE_DIR, f"battery_plot_{date}.png")
    plt.savefig(plot_path)
    daily_plot_paths.append((str(date), plot_path))
    plt.close()

# ==== DeviceStatus: rohe Codes ====
#

# ==== DeviceStatus: Bit-Dekodierung ====
status_bits = {
    0: "Warm-up Phase",
    1: "Gas Sensor not ready",
    2: "Temp/Humidity Sensor not ready",
    3: "Fan error",
    4: "Laser error",
    5: "Fan speed warning",
    6: "Laser power warning",
    7: "Humidity/Temp out of range",
    8: "VOC algorithm not stable",
    9: "VOC sensor communication error",
    10: "Forced recalibration",
    11: "Automatic recalibration"
}

bit_counts = {bit: 0 for bit in status_bits.keys()}

for status_str in df["DeviceStatus"].dropna().astype(str):
    try:
        status = int(status_str, 0)  # unterstützt '0x' Hex-Werte und Dezimalzahlen
        for bit in status_bits:
            if status & (1 << bit):
                bit_counts[bit] += 1
    except ValueError:
        continue

#


# ==== PDF-Report erzeugen ====
pdf = FPDF()
pdf.set_font("Arial", size=12)

pdf.add_page()
pdf.set_font("Arial", style="B", size=14)
pdf.cell(0, 10, "Visualisierung der Akkudaten", ln=True, align="C")
pdf.ln(5)
pdf.set_font("Arial", size=12)
pdf.ln(2)
for _, plot_path in daily_plot_paths:
    pdf.image(plot_path, x=10, y=pdf.get_y(), w=180)
    pdf.ln(80)

# --- Neue Seite für Tabelle und Text ---
pdf.add_page()

pdf.set_font("Arial", style="B", size=14)
pdf.cell(0, 10, "Daten Akkuspannung", ln=True, align="C")
pdf.ln(5)

table_width = 45 + 35 + 30 + 40
x_start = (210 - table_width) / 2  # A4-Seitenbreite ist 210 mm
pdf.set_x(x_start)
pdf.cell(45, 6, "Timestamp", border=1)
pdf.cell(35, 6, "Spannung [V]", border=1)
pdf.cell(30, 6, "SOC [%]", border=1)
pdf.cell(40, 6, "Min oder Max", border=1)
pdf.ln()

pdf.set_font("Arial", size=9)
t_min = df.loc[df["Battery_Volt"] == min_v].iloc[0]
pdf.set_x(x_start)
pdf.cell(45, 6, str(t_min["timestamp"]), border=1)
pdf.cell(35, 6, f"{t_min['Battery_Volt']:.2f}", border=1)
pdf.cell(30, 6, f"{t_min['Battery_Pct']:.1f}", border=1)
pdf.cell(40, 6, "Min", border=1)
pdf.ln()

t_max = df.loc[df["Battery_Volt"] == max_v].iloc[0]
pdf.set_x(x_start)
pdf.cell(45, 6, str(t_max["timestamp"]), border=1)
pdf.cell(35, 6, f"{t_max['Battery_Volt']:.2f}", border=1)
pdf.cell(30, 6, f"{t_max['Battery_Pct']:.1f}", border=1)
pdf.cell(40, 6, "Max", border=1)
pdf.ln(10)

# --- Neue Seite für Statusbit-Tabelle ---
pdf.add_page()
pdf.set_font("Arial", style="B", size=14)
pdf.cell(0, 10, "Sensorstatus-Bits", ln=True, align="C")
pdf.ln(5)
pdf.cell(20, 10, "Bit", border=1)
pdf.cell(100, 10, "Beschreibung", border=1)
pdf.cell(40, 10, "Häufigkeit", border=1)
pdf.ln()

pdf.set_font("Arial", size=11)
for bit, count in bit_counts.items():
    beschreibung = status_bits[bit]
    pdf.cell(20, 10, str(bit), border=1)
    pdf.cell(100, 10, beschreibung, border=1)
    pdf.cell(40, 10, f"{count} mal", border=1)
    pdf.ln()

latest_time = df["timestamp"].max().strftime("%Y-%m-%d_%H-%M-%S")
output_path = os.path.join(BASE_DIR, "..", f"datenanalyse_{latest_time}.pdf")
pdf.output(output_path)

print(f"PDF gespeichert unter: {output_path}")
import subprocess
import platform

system = platform.system()
try:
    if system == "Darwin":
        subprocess.run(["open", output_path], check=False)
    elif system == "Windows":
        os.startfile(output_path)
    elif system == "Linux":
        subprocess.run(["xdg-open", output_path], check=False)
    else:
        print(f"PDF gespeichert unter: {output_path}")
except Exception as e:
    print(f"PDF gespeichert unter: {output_path}")
    print(f"Fehler beim Öffnen der Datei: {e}")