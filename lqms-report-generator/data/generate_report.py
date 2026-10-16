import os
import platform
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# Erzwinge Agg Backend früh
os.environ['MPLBACKEND'] = 'Agg'


def show_progress_window():
    root = tk.Tk()
    root.title("LQMS Report")
    # Fenstergröße und zentrieren
    w, h = 350, 100
    ws = root.winfo_screenwidth()
    hs = root.winfo_screenheight()
    x, y = (ws - w) // 2, (hs - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    root.resizable(False, False)

    lbl = ttk.Label(root, text="Report wird generiert…")
    lbl.pack(pady=(20, 5))
    pb = ttk.Progressbar(root, mode='indeterminate')
    pb.pack(fill='x', padx=20)
    pb.start()
    root.update()
    root.lift()
    root.attributes("-topmost", True)
    root.after_idle(root.attributes, "-topmost", False)
    return root, pb, lbl


# Einheitliche Farben für Graph und Balken (aktuell: Pastellfarben)
COLOR_GREEN  = "#A8E6CF"  # sanftes Pastellgrün   # Alternative kräftig: "#00A03E"
COLOR_ORANGE = "#FFD3B6"  # sanftes Pastellorange # Alternative kräftig: "#FFA500"
COLOR_RED    = "#FF8C94"  # sanftes Pastellrot    # Alternative kräftig: "#E60000"
COLOR_VOC    = "#5DADE2"  # leicht dunkleres Blau
COLOR_NOX    = "#800080"  # violett

def hex2rgb(hex_color):
    """Konvertiert einen Hex-Farbstring '#RRGGBB' in ein RGB-Tupel."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def get_script_dir():
    """
    Returns the directory where this script is located.
    """
    return os.path.dirname(os.path.abspath(__file__))

def show_msgbox(title, message):
    """Einfaches Terminal-Popup-Äquivalent."""
    print(f"{title}: {message}")

def generate_report():
    import warnings
    warnings.simplefilter("ignore", DeprecationWarning)
    import sys
    import io
    from datetime import datetime
    import pandas as pd
    import matplotlib.pyplot as plt
    from fpdf import FPDF

    try:
        import platform        # sicherstellen, dass hier das Modul verwendet wird
        # Betriebssystem prüfen, Windows 10 nicht unterstützt
        if platform.system() == "Windows" and platform.release().startswith("10"):
            messagebox.showerror("LQMS Report", "Windows 10 wird nicht unterstützt, bitte Windows 11 verwenden")
        # ermittel Basisordner je nach Modus
        if getattr(sys, "frozen", False):
            exe_dir   = os.path.dirname(sys.executable)
            # zwei Ebenen: ...\data\dist → eine Ebene hoch zu ...\data
            base_path = os.path.abspath(os.path.join(exe_dir, ".."))
        else:
            base_path = os.path.dirname(__file__)

        pictures_dir = os.path.join(base_path, "pictures")

        data_file    = os.path.join(base_path, "data.csv")
        pictures_dir = os.path.join(base_path, "pictures")
        logo_path    = os.path.join(pictures_dir, "logo.png")  # optional: eigenes Logo unter pictures/logo.png ablegen

        print("base_path  =", base_path)
        print("data_file  =", data_file)
        print("pictures_dir =", pictures_dir)
        print("logo_path  =", logo_path)


        if not os.path.exists(data_file):
            raise FileNotFoundError(f"Datei nicht gefunden: {data_file}")

        # CSV laden und filtern
        lines = []

        with open(data_file, 'rb') as f:        
            for raw_line in f:
                try:
                    line = raw_line.decode('utf-8').strip()
                    lines.append(line)
                except UnicodeDecodeError:
                    continue  # ungültige Binärzeile überspringen

        expected_fields = 16  # So viele Spalten erwarten wir pro Zeile (neues CSV-Format)
        valid_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue  # leere Zeile überspringen
            fields = line.split(',')
            if "Zeit" in line and "PM1.0" in line:
                valid_lines.insert(0, line + '\n')
                continue
            if len(fields) != expected_fields:
                continue  # Zeile hat zu viele oder zu wenige Felder → ignorieren
            ts_part = fields[0].strip()
            try:
                datetime.strptime(ts_part, "%Y-%m-%dT%H:%M:%S")
                valid_lines.append(line + '\n')
            except ValueError:
                continue

        # Datei nicht überschreiben, nur Daten für spätere Verarbeitung behalten
        filtered_csv_lines = valid_lines

        import io
        df = pd.read_csv(io.StringIO(''.join(filtered_csv_lines)), delimiter=",")
        df.rename(columns={
            "Zeit": "timestamp",
            "Temperatur": "Temperature",
            "Feuchte": "Humidity",
            "Aktivitaet": "Activity",
            "PM10.0": "PM10",
            "AkkuVolt": "Battery_Volt",
            "AkkuProzent": "Battery_Pct"
        }, inplace=True)
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
        df = df.dropna(subset=['timestamp'])
        df = df[df['DeviceStatus'] != '0xFFFF']
        # Entferne Zeilen, bei denen alle PM-Werte UND NOx gleichzeitig am Limit sind
        pm_limit = 6553.5
        nox_limit = 3276.7
        df = df[~(
            (df["PM1.0"] == pm_limit) &
            (df["PM2.5"] == pm_limit) &
            (df["PM4.0"] == pm_limit) &
            (df["PM10"] == pm_limit) &
            (df["NOx"] == nox_limit)
        )]

        # Entferne zusätzlich Zeilen, bei denen nur NOx am Limit ist
        df = df[df["NOx"] != nox_limit]

        if df.empty:
            raise ValueError("Keine gültigen Zeitstempel in der CSV-Datei gefunden.")
        df['Feinstaub'] = df[['PM1.0','PM2.5','PM4.0','PM10']].max(axis=1)

        # Aktivitäten-Split: nur lange zusammenhängende Abschnitte behalten (mind. 30 Punkte)
        cleaned_segments = []
        for activity in df["Activity"].unique():
            df_act = df[df["Activity"] == activity].copy()
            df_act = df_act.sort_values("timestamp")
            df_act["time_diff"] = df_act["timestamp"].diff().fillna(pd.Timedelta(seconds=0))
            segment_id = 0
            segment_ids = []
            for diff in df_act["time_diff"]:
                if diff > pd.Timedelta(minutes=5):  # definierter Bruch zwischen Segmenten
                    segment_id += 1
                segment_ids.append(segment_id)
            df_act["segment"] = segment_ids
            grouped = df_act.groupby("segment")
            for _, segment_df in grouped:
                if len(segment_df) >= 30:
                    cleaned_segments.append(segment_df.drop(columns=["time_diff", "segment"]))
        # Nur gültige Abschnitte beibehalten
        if cleaned_segments:
            df = pd.concat(cleaned_segments).sort_values("timestamp").reset_index(drop=True)
        else:
            raise ValueError("Keine gültigen Aktivitätsabschnitte mit ausreichend Daten gefunden.")

        # Gesamt‐Zeitraum (für Dateiname etc. beibehalten)
        start_dt = df['timestamp'].iloc[0]
        end_dt   = df['timestamp'].iloc[-1]

        # 1) Alle Intervalle zwischen Messpunkten
        timedeltas = df['timestamp'].diff().dropna()

        # 2) Typische Abtastrate (Median)
        median_interval = timedeltas.median()

        # 3) Schwellenwert festlegen (hier 2× Median, anpassen nach Sensor-Frequenz)
        max_valid_gap = median_interval * 2

        # 4) Nur „kurze” Intervalle aufsummieren
        valid_intervals = timedeltas[timedeltas <= max_valid_gap]
        duration = valid_intervals.sum()

        # Dauer in Tage/Stunden/Minuten zerlegen
        days    = duration.days
        hours   = duration.seconds // 3600
        minutes = (duration.seconds % 3600) // 60

        if days == 0:
            duration_str = f"{hours} Stunden {minutes} Minuten"
        else:
            duration_str = f"{days} Tage {hours} Stunden"



        # Aktivitäts‐Limits
        most_common_activity = df["Activity"].mode()[0]
        limits = { act:(625,1250) for act in df["Activity"].unique() }
        green_limit, orange_limit = limits.get(most_common_activity, (625,1250))
        df_filtered = df  # gesamte Messung für die erste Seite
        df_all = df  # gesamte Messung für die Verteilung auf Seite 1

        # Gesamt‐Statistiken (nur relevante Messgrößen, jetzt über gesamten Zeitraum)
        stats = {
            'Feinstaub': df_all['Feinstaub'].mean(),
            'VOC':   df_all['VOC'].mean(),
            'NOx': df_all['NOx'].mean(),
            'Temperature':  df_all['Temperature'].mean(),
            'Humidity':     df_all['Humidity'].mean(),
            'Lautstaerke_dB': df_all['Lautstaerke_D_B'].mean() if 'Lautstaerke_D_B' in df_all else df_all['Lautstaerke_dB'].mean()
        }

        # PDF anlegen
        pdf = FPDF()
        pdf.add_page()
        if os.path.exists(logo_path):
            pdf.image(logo_path, x=pdf.w - 40, y=pdf.h - 20, w=30)

        # TITEL Gesamt
        pdf.set_font("Arial", style="B", size=16)
        pdf.cell(200, 10, txt="Luftqualitätsbericht - GESAMT", ln=True, align='C')
        pdf.ln(8)

        # Gesamt‐Übersicht
        pdf.set_font("Arial", size=12)
        pdf.cell(50, 8, "Zeitraum:", ln=False)
        pdf.cell(0, 8, f"{start_dt} - {end_dt}", ln=True)
        pdf.cell(50, 8, "Dauer:", ln=False)
        pdf.cell(0, 8, duration_str, ln=True)
        pdf.cell(50, 8, "Messpunkte:", ln=False)
        pdf.cell(0, 8, str(len(df)), ln=True)
        pdf.cell(50, 8, "Häufigste Aktivität:", ln=False)
        pdf.cell(0, 8, most_common_activity, ln=True)
        pdf.ln(6)

        # Stats‐Tabelle mit Max-Werten
        pdf.set_font("Arial", style="B", size=11)
        pdf.cell(50, 6, "Messgrösse", ln=False)
        pdf.cell(40, 6, "Ø Durchschnitt", ln=False)
        pdf.cell(40, 6, "Maximalwert", ln=True)
        pdf.set_font("Arial", style="", size=11)
        for label, val in stats.items():
            max_val = df_filtered[label].max()
            if label == "Feinstaub":
                display_label = "Feinstaub [µg/m³]"
            elif label == "VOC":
                display_label = "VOC [ppb]"
            elif label == "NOx":
                display_label = "NOx [ppb]"
            elif label == "Temperature":
                display_label = "Temperatur [°C]"
            elif label == "Humidity":
                display_label = "Luftfeuchtigkeit [%]"
            elif label == "Lautstaerke_dB":
                display_label = "Lautstärke [dB]"
            else:
                display_label = label
            pdf.cell(50, 6, f"{display_label}:", ln=False)
            pdf.cell(40, 6, f"{val:.2f}", ln=False)
            pdf.cell(40, 6, f"{max_val:.2f}", ln=True)
        pdf.ln(6)

        # Plot Gesamt
        fig, ax1 = plt.subplots(figsize=(10, 5))
        times = df['timestamp']
        a_staub = df['Feinstaub']
        def get_color(val):
            if val <= green_limit: return COLOR_GREEN
            if val <= orange_limit: return COLOR_ORANGE
            return COLOR_RED
        for i in range(1, len(df)):
            t0, t1 = times.iloc[i-1], times.iloc[i]
            y0, y1 = a_staub.iloc[i-1], a_staub.iloc[i]
            c0, c1 = get_color(y0), get_color(y1)
            if c0 == c1:
                ax1.plot([t0, t1], [y0, y1], color=c0)
            else:
                for thr in (green_limit, orange_limit):
                    if (y0-thr)*(y1-thr) < 0:
                        ratio = (thr-y0)/(y1-y0)
                        ts = t0 + (t1-t0)*ratio
                        ax1.plot([t0, ts], [y0, thr], color=c0)
                        ax1.plot([ts, t1], [thr, y1], color=c1)
                        break
        ax2 = ax1.twinx()
        ax2.plot(times, df["VOC"], color=COLOR_VOC)
        ax2.plot(times, df["NOx"], color=COLOR_NOX)
        ax2.set_ylabel("VOC (blau) / NOx (violett)", color="black")
        ax1.set_ylabel("Feinstaub", color="black")
        plt.tight_layout()
        plot_path = os.path.join(pictures_dir, "plot.png")
        plt.savefig(plot_path)
        plt.close()

        pdf.ln(2)
        pdf.image(plot_path, x=10, y=pdf.get_y(), w=180)
        pdf.ln(90)

        # Fußnoten
        pdf.set_x(25)
        pdf.set_font("Arial", size=7)
        pdf.multi_cell(0, 5, "*Feinstaub ist Staub, der tief in die Lunge vordringen kann und gesundheitliche Risiken birgt.")
        pdf.set_x(25)
        pdf.multi_cell(0, 5, "*VOC (flüchtige organische Verbindungen) können bereits in geringer Konzentration gesundheitlich bedenklich sein.")
        pdf.set_x(25)
        pdf.multi_cell(0, 5, "*NOx (Stickoxide) können Atemwege reizen und zur Bildung von bodennahem Ozon beitragen.")
        pdf.ln(4)

        # Verteilungsbalken Gesamt
        bar_width = 180; x = 10; y = pdf.get_y()
        total = len(df_all)
        gp = (df_all['Feinstaub'] <= green_limit).sum() / total * 100
        op = ((df_all['Feinstaub'] > green_limit) & (df_all['Feinstaub'] <= orange_limit)).sum() / total * 100
        rp = 100 - gp - op
        gw = bar_width * gp / 100; ow = bar_width * op / 100; rw = bar_width - gw - ow
        pdf.set_fill_color(*hex2rgb(COLOR_GREEN));  pdf.rect(x, y, gw, 6, 'F')
        pdf.set_fill_color(*hex2rgb(COLOR_ORANGE)); pdf.rect(x+gw, y, ow, 6, 'F')
        pdf.set_fill_color(*hex2rgb(COLOR_RED));    pdf.rect(x+gw+ow, y, rw, 6, 'F')
                
        # nach dem Zeichnen der Balken:
        pdf.set_font("Arial", size=8)
        pdf.set_text_color(255, 255, 255)
        # Prozentwerte berechnen
        gp_pct = gp
        op_pct = op
        rp_pct = rp
        # Segment-Breiten
        bar_width = 180
        gw = bar_width * gp_pct / 100
        ow = bar_width * op_pct / 100
        rw = bar_width - gw - ow
        # Prozenttexte mittig platzieren (y+4 vertikal, x+offset horizontal)
        if gw > 3:
            pdf.text(10 + gw/2 - 6, y + 4, f"{int(round(gp_pct))}%")
        if ow > 3:
            pdf.text(10 + gw + ow/2 - 6, y + 4, f"{int(round(op_pct))}%")
        if rw > 3:
            pdf.text(10 + gw + ow + rw/2 - 6, y + 4, f"{int(round(rp_pct))}%")
        pdf.set_text_color(0, 0, 0)

        pdf.ln(8)
        pdf.set_font("Arial", size=8)
        pdf.write(4, "Anteil der Messzeit in ")
        pdf.set_text_color(*hex2rgb(COLOR_GREEN)); pdf.set_font("Arial", style="B", size=8); pdf.write(4, "grün (Feinstaub <= 625 ug/m3)")
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=8); pdf.write(4, ", ")
        pdf.set_text_color(*hex2rgb(COLOR_ORANGE)); pdf.set_font("Arial", style="B", size=8); pdf.write(4, "orange (625 < Feinstaub <= 1250 ug/m3)")
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=8); pdf.write(4, ", ")
        pdf.set_text_color(*hex2rgb(COLOR_RED)); pdf.set_font("Arial", style="B", size=8); pdf.write(4, "rot (Feinstaub > 1250 ug/m3)")
        pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=8)
        pdf.ln(5)
        
        # Erläuterungen zu PM-Werten und A_Staub
        pdf.set_font("Arial", size=8)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(5)
        pdf.multi_cell(0, 5,
            "PM1.0, PM2.5, PM4.0 und PM10 geben die Konzentration von Feinstaubpartikeln an, deren aerodynamischer Durchmesser jeweils kleiner als 1.0 um, 2.5 um, 4.0 um bzw. 10 um ist. "
            "Je kleiner die Partikel, desto tiefer können sie in die Atemwege vordringen und desto grösser ist ihr gesundheitliches Risiko. "
            "Der Feinstaub-Wert im Bericht wird für jeden Messzeitpunkt als der höchste der vier PM-Werte berechnet. "
            "Er stellt damit die maximale gemessene Feinstaubbelastung zu einem Zeitpunkt dar und dient als Richtwert für die Luftqualität.")
        pdf.ln(1)
        # Lautstärke > 85 dB Auswertung (Gesamt, jetzt gesamter Zeitraum)
        time_above_85db = df_all[df_all["Lautstaerke_dB"] > 85]["timestamp"].diff().fillna(pd.Timedelta(seconds=0))
        total_85db = time_above_85db[time_above_85db <= max_valid_gap].sum()
        mins_85db = round(total_85db.total_seconds() / 60)
        db85_text = f"Lautstärke über 85 dB kann das Gehör schädigen. Während der Messung wurde insgesamt {mins_85db} Minuten über diesem Schwellenwert gearbeitet."
        if mins_85db > 0:
            pdf.set_text_color(255, 0, 0)
        pdf.multi_cell(0, 5, db85_text)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(1)
        # Atemschutz-Link am Ende der Seite
        pdf.set_font("Arial", size=8)
        pdf.set_text_color(0, 0, 0)
        pdf.write(4, "Hinweis: Bei erhöhter Belastung geeigneten Atemschutz tragen (z. B. FFP2/FFP3-Maske).")
        pdf.set_text_color(0, 0, 255)
        pass  # (firmenspezifischer Produktlink entfernt)
        pdf.set_text_color(0, 0, 0)

        # Detailseiten je Aktivität
        for activity in df["Activity"].unique():
            df_act = df[df["Activity"] == activity]

            # Seite anlegen
            pdf.add_page()
            if os.path.exists(logo_path):
                pdf.image(logo_path, x=pdf.w - 40, y=pdf.h - 20, w=30)

            # Titel mit ausgeschriebenen Abkürzungen
            title_text = activity.replace("Laserschw.", "Laserschweissen").replace("Lichtbogen", "Lichtbogenhandschweissen").replace("Loesungsm.", "Lösungsmittel")
            pdf.set_font("Arial", style="B", size=16)
            pdf.cell(200, 10, txt=f"Luftqualitätsbericht - {title_text}", ln=True, align='C')
            pdf.ln(6)

            # Zeitraum, Dauer, Messpunkte
            start_a = df_act['timestamp'].iloc[0]
            end_a   = df_act['timestamp'].iloc[-1]

            # Dauer nur aus tatsächlichen Mess-Intervallen zusammensetzen:
            timedeltas_a = df_act['timestamp'].diff().dropna()
            median_a     = timedeltas_a.median()
            max_gap_a    = median_a * 2  # 2× typische Abtastrate
            valid_a      = timedeltas_a[timedeltas_a <= max_gap_a]
            dur          = valid_a.sum()

            # In Tage, Stunden und Minuten zerlegen
            days_a    = dur.days
            hours_a   = dur.seconds // 3600
            minutes_a = (dur.seconds % 3600) // 60

            if days_a == 0:
                dur_str = f"{hours_a} Stunden {minutes_a} Minuten"
            else:
                dur_str = f"{days_a} Tage {hours_a} Stunden"

            # Zeitraum, Dauer, Messpunkte (nur einmal)
            pdf.set_font("Arial", size=12)
            pdf.cell(50, 8, "Zeitraum:", ln=False)
            pdf.cell(0, 8, f"{start_a} - {end_a}", ln=True)
            pdf.cell(50, 8, "Dauer:", ln=False)
            pdf.cell(0, 8, dur_str, ln=True)
            pdf.cell(50, 8, "Messpunkte:", ln=False)
            pdf.cell(0, 8, str(len(df_act)), ln=True)
            pdf.ln(6)

            # Aktivitäts-spezifische Stats (nur relevante Messgrößen)
            stats_act = {
                'Feinstaub': df_act['Feinstaub'].mean(),
                'VOC':   df_act['VOC'].mean(),
                'NOx': df_act['NOx'].mean(),
                'Temperature':  df_act['Temperature'].mean(),
                'Humidity':     df_act['Humidity'].mean(),
                'Lautstaerke_dB': df_act['Lautstaerke_D_B'].mean() if 'Lautstaerke_D_B' in df_act else df_act['Lautstaerke_dB'].mean()
            }

            pdf.set_font("Arial", style="B", size=11)
            pdf.cell(50, 6, "Messgrösse", ln=False)
            pdf.cell(40, 6, "Ø Durchschnitt", ln=False)
            pdf.cell(40, 6, "Maximalwert", ln=True)
            pdf.set_font("Arial", style="", size=11)

            for lbl, val in stats_act.items():
                max_val = df_act[lbl].max()
                if lbl == "Feinstaub":
                    display_lbl = "Feinstaub [µg/m³]"
                elif lbl == "VOC":
                    display_lbl = "VOC [ppb]"
                elif lbl == "NOx":
                    display_lbl = "NOx [ppb]"
                elif lbl == "Temperature":
                    display_lbl = "Temperatur [°C]"
                elif lbl == "Humidity":
                    display_lbl = "Luftfeuchtigkeit [%]"
                elif lbl == "Lautstaerke_dB":
                    display_lbl = "Lautstärke [dB]"
                else:
                    display_lbl = lbl
                pdf.cell(50, 6, f"{display_lbl}:", ln=False)
                pdf.cell(40, 6, f"{val:.2f}", ln=False)
                pdf.cell(40, 6, f"{max_val:.2f}", ln=True)

            pdf.ln(6)

            # Plot Aktivität
            df_plot = df.copy()
            df_plot.loc[df_plot['Activity'] != activity, ['Feinstaub', 'VOC', 'NOx']] = pd.NA
            fig, ax1 = plt.subplots(figsize=(10, 5))
            times_act = df_plot['timestamp']
            a_act     = df_plot['Feinstaub']
            def get_color_act(v):
                if v <= green_limit: return COLOR_GREEN
                if v <= orange_limit: return COLOR_ORANGE
                return COLOR_RED
            for i in range(1, len(df_plot)):
                t0, t1 = times_act.iloc[i-1], times_act.iloc[i]
                y0, y1 = a_act.iloc[i-1], a_act.iloc[i]
                c0, c1 = get_color_act(y0), get_color_act(y1)
                if c0 == c1:
                    ax1.plot([t0, t1], [y0, y1], color=c0)
                else:
                    for thr in (green_limit, orange_limit):
                        if (y0-thr)*(y1-thr) < 0:
                            ratio = (thr-y0)/(y1-y0)
                            ts = t0 + (t1-t0)*ratio
                            ax1.plot([t0, ts], [y0, thr], color=c0)
                            ax1.plot([ts, t1], [thr, y1], color=c1)
                            break
            ax2 = ax1.twinx()
            ax2.plot(times_act, df_plot["VOC"], color=COLOR_VOC)
            ax2.plot(times_act, df_plot["NOx"], color=COLOR_NOX)
            ax2.set_ylabel("VOC (blau) / NOx (violett)", color="black")
            ax1.set_ylabel("Feinstaub", color="black")
            plt.tight_layout()
            safe_activity = activity.replace("/", "_")
            plot_act = os.path.join(pictures_dir, f"plot_{safe_activity}.png")
            plt.savefig(plot_act)
            plt.close()

            pdf.ln(2)
            safe_activity = activity.replace("/", "_")
            plot_act = os.path.join(pictures_dir, f"plot_{safe_activity}.png")
            pdf.image(plot_act, x=10, y=pdf.get_y(), w=180)
            pdf.ln(90)

            # Fußnoten Aktivität
            pdf.set_x(25)
            pdf.set_font("Arial", size=7)
            pdf.multi_cell(0, 5, "*Feinstaub ist Staub, der tief in die Lunge vordringen kann und gesundheitliche Risiken birgt.")
            pdf.set_x(25)
            pdf.multi_cell(0, 5, "*VOC (flüchtige organische Verbindungen) können bereits in geringer Konzentration gesundheitlich bedenklich sein.")
            pdf.set_x(25)
            pdf.multi_cell(0, 5, "*NOx (Stickoxide) können Atemwege reizen und zur Bildung von bodennahem Ozon beitragen.")
            pdf.ln(4)

            # Verteilungsbalken Aktivität
            bar_w = 180; x0 = 10; y0 = pdf.get_y()
            total_a = len(df_act)
            gp_a = (df_act['Feinstaub'] <= green_limit).sum()/total_a*100
            op_a = ((df_act['Feinstaub'] > green_limit) & (df_act['Feinstaub'] <= orange_limit)).sum()/total_a*100
            rp_a = (df_act['Feinstaub'] > orange_limit).sum()/total_a*100
            gw_a = bar_w * gp_a/100; ow_a = bar_w * op_a/100; rw_a = bar_w - gw_a - ow_a

            pdf.set_fill_color(*hex2rgb(COLOR_GREEN));  pdf.rect(x0, y0, gw_a, 6, 'F')
            pdf.set_fill_color(*hex2rgb(COLOR_ORANGE));pdf.rect(x0+gw_a, y0, ow_a, 6, 'F')
            pdf.set_fill_color(*hex2rgb(COLOR_RED));   pdf.rect(x0+gw_a+ow_a, y0, rw_a, 6, 'F')
            pdf.set_text_color(0, 0, 0)

            # Prozentwerte berechnen
            total = len(df_act)  # in der Aktivitätsschleife
            gp_pct = (df_act['Feinstaub'] <= green_limit).sum() / total * 100
            op_pct = ((df_act['Feinstaub'] > green_limit) & (df_act['Feinstaub'] <= orange_limit)).sum() / total * 100
            rp_pct = 100 - gp_pct - op_pct

            # Schrift auf Weiß setzen
            pdf.set_text_color(255, 255, 255)
            if gw_a > 3:
                pdf.text(x0 + gw_a/2 - 6, y0 + 4, f"{int(round(gp_pct))}%")
            if ow_a > 3:
                pdf.text(x0 + gw_a + ow_a/2 - 6, y0 + 4, f"{int(round(op_pct))}%")
            if rw_a > 3:
                pdf.text(x0 + gw_a + ow_a + rw_a/2 - 6, y0 + 4, f"{int(round(rp_pct))}%")
            # Zurück auf Schwarz
            pdf.set_text_color(0, 0, 0)

            pdf.ln(8)
            pdf.set_font("Arial", size=8)
            pdf.write(4, "Anteil der Messzeit in ")
            pdf.set_text_color(*hex2rgb(COLOR_GREEN)); pdf.set_font("Arial", style="B", size=8); pdf.write(4, "grün (Feinstaub <= 625 ug/m3)")
            pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=8); pdf.write(4, ", ")
            pdf.set_text_color(*hex2rgb(COLOR_ORANGE)); pdf.set_font("Arial", style="B", size=8); pdf.write(4, "orange (625 < Feinstaub <= 1250 ug/m3)")
            pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=8); pdf.write(4, ", ")
            pdf.set_text_color(*hex2rgb(COLOR_RED)); pdf.set_font("Arial", style="B", size=8); pdf.write(4, "rot (Feinstaub > 1250 ug/m3)")
            pdf.set_text_color(0, 0, 0); pdf.set_font("Arial", size=8)
            pdf.ln(5)
            
            # Erläuterungen zu PM-Werten und A_Staub
            pdf.set_font("Arial", size=8)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(5)
            pdf.multi_cell(0, 5,
                "PM1.0, PM2.5, PM4.0 und PM10 geben die Konzentration von Feinstaubpartikeln an, deren aerodynamischer Durchmesser jeweils kleiner als 1.0 um, 2.5 um, 4.0 um bzw. 10 um ist. "
                "Je kleiner die Partikel, desto tiefer können sie in die Atemwege vordringen und desto grösser ist ihr gesundheitliches Risiko. "
                "Der Feinstaub-Wert im Bericht wird für jeden Messzeitpunkt als der höchste der vier PM-Werte berechnet. "
                "Er stellt damit die maximale gemessene Feinstaubbelastung zu einem Zeitpunkt dar und dient als Richtwert für die Luftqualität.")
            pdf.ln(2)
            # Lautstärke > 85 dB Auswertung (Aktivität, konsistente Berechnung)
            df_laut_a = df_act[["timestamp", "Lautstaerke_dB"]].copy()
            df_laut_a["delta"] = df_laut_a["timestamp"].diff()
            df_laut_a["valid"] = df_laut_a["delta"] <= max_gap_a
            dauer_85_a = df_laut_a[(df_laut_a["Lautstaerke_dB"] > 85) & (df_laut_a["valid"])]["delta"].sum()
            mins_85db_a = round(dauer_85_a.total_seconds() / 60)
            db85_text_a = f"Lautstärke über 85 dB kann das Gehör schädigen. Während dieser Aktivität wurde insgesamt {mins_85db_a} Minuten über diesem Schwellenwert gearbeitet."
            if mins_85db_a > 0:
                pdf.set_text_color(255, 0, 0)
            pdf.multi_cell(0, 5, db85_text_a)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)
            # Atemschutz-Link am Ende der Aktivitätsseite
            pdf.set_font("Arial", size=8)
            pdf.set_text_color(0, 0, 0)
            pdf.write(4, "Hinweis: Bei erhöhter Belastung geeigneten Atemschutz tragen (z. B. FFP2/FFP3-Maske).")
            pdf.set_text_color(0, 0, 255)
            pass  # (firmenspezifischer Produktlink entfernt)
            pdf.set_text_color(0, 0, 0)

        # --- Neue Seite: Lautstärkeauswertung (Gesamt) ---
        pdf.add_page()
        if os.path.exists(logo_path):
            pdf.image(logo_path, x=pdf.w - 40, y=pdf.h - 20, w=30)
        pdf.set_font("Arial", style="B", size=16)
        pdf.cell(200, 10, txt="Lautstärkeauswertung (Gesamt)", ln=True, align='C')
        pdf.ln(6)

        # Beschreibung Suva
        pdf.set_font("Arial", size=9)
        pdf.multi_cell(0, 5,
            "Gemäss SUVA kann eine dauerhafte Lärmbelastung ab 85 dB das Gehör schädigen. "
            "Bei über 85 dB ist ein Gehörschutz vorgeschrieben. "
            "Dieser Bericht analysiert die Dauer und Anteile der Messung über und unter diesem Grenzwert.")
        pdf.ln(4)

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(df['timestamp'], df['Lautstaerke_dB'], color='#A8CFFF', linewidth=0.7)  # pastellblau
        ax.axhline(y=85, color='#FF8C94', linestyle='--', linewidth=1)
        ax.annotate("85 dB", xy=(1.01, 85), xycoords=('axes fraction', 'data'),
                    va='center', ha='left', fontsize=8, color='#FF8C94')
        ax.set_ylabel("dB")
        plt.tight_layout()
        plot_db = os.path.join(pictures_dir, "plot_db.png")
        plt.savefig(plot_db)
        plt.close()
        pdf.image(plot_db, x=10, y=pdf.get_y(), w=180)
        pdf.ln(90)

        # Wiederverwendung des zuvor berechneten Werts
        # 'mins_85db' wurde weiter oben im Bericht bereits korrekt berechnet

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", size=10)
        pdf.ln(2)
        pdf.cell(0, 6, f"Lautstärke über 85 dB während des Messzeitraums: {mins_85db} Minuten", ln=True)
        pdf.ln(4)

        pdf.set_font("Arial", style="B", size=11)
        pdf.cell(70, 6, "Aktivität", ln=False)
        pdf.cell(40, 6, "Ø Lautstärke [dB]", ln=False)
        pdf.cell(40, 6, "Maximalwert [dB]", ln=True)
        pdf.set_font("Arial", size=11)

        # Aktivitäten-Stats-Liste für Sortierung
        activity_stats = []
        for activity in df["Activity"].unique():
            df_act = df[df["Activity"] == activity]
            avg_db = df_act["Lautstaerke_dB"].mean()
            max_db = df_act["Lautstaerke_dB"].max()
            activity_stats.append((activity, avg_db, max_db))

        # Zuerst nach Durchschnitt, dann nach Maximalwert sortieren (beides absteigend)
        activity_stats.sort(key=lambda x: (x[1], x[2]), reverse=True)

        for activity, avg_db, max_db in activity_stats:
            pdf.cell(70, 6, activity, ln=False)

            if avg_db > 85:
                pdf.set_text_color(255, 0, 0)
            pdf.cell(40, 6, f"{avg_db:.1f}", ln=False)
            pdf.set_text_color(0, 0, 0)

            if max_db > 90:
                pdf.set_text_color(255, 0, 0)
            pdf.cell(40, 6, f"{max_db:.1f}", ln=True)
            pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        # Report speichern
        # Save to ../report.pdf (top-level) with timestamp in filename
        last_ts = df['timestamp'].iloc[-1]
        timestamp_str = last_ts.strftime("%Y-%m-%d_%H-%M-%S")
        out_path = os.path.abspath(os.path.join(base_path, "..", f"report_{timestamp_str}.pdf"))

        pdf.output(out_path)

        return out_path

    except Exception as e:
        show_msgbox("LQMS Report", f"Fehler:\n{e}")

import os        # ganz oben schon da
# … und tkinter/ttk/messagebox, threading …

def on_success(pdf_path):
    # Fortschrittsbalken beenden und auf 100 % setzen
    prog_bar.stop()
    prog_bar.config(mode='determinate', value=100)
    # Label anpassen
    prog_lbl.config(text="Report erfolgreich erstellt!")
    # PDF automatisch öffnen, ohne Nutzerabfrage
    try:
        if platform.system() == "Windows":
            os.startfile(pdf_path)
        elif platform.system() == "Darwin":
            import subprocess
            subprocess.call(["open", pdf_path])
        elif platform.system() == "Linux":
            import subprocess
            subprocess.call(["xdg-open", pdf_path])
    except Exception as e:
        messagebox.showerror("LQMS Report", f"PDF konnte nicht geöffnet werden:\n{e}")
    # Fenster in 3 Sek. schließen
    prog_win.after(3000, prog_win.destroy)

def on_error(exc):
    prog_bar.stop()
    prog_lbl.config(text="Fehler beim Erstellen")
    messagebox.showerror("LQMS Report - Fehler", str(exc))
    prog_win.after(3000, prog_win.destroy)

if __name__ == '__main__':
    prog_win, prog_bar, prog_lbl = show_progress_window()

    def worker():
        try:
            pdf_path = generate_report()        # Pfad zurückbekommen
            prog_win.after(0, lambda: on_success(pdf_path))
        except Exception as e:
            prog_win.after(0, lambda: on_error(e))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    prog_win.mainloop()




