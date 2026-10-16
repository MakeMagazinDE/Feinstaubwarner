#include <Wire.h>
#include <RTClib.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_GFX.h>
#include <SensirionI2cSen66.h>
#include <SPI.h>
#include <SD.h>
#include <Adafruit_NeoPixel.h>

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define OLED_ADDR     0x3C
#define BATTERY_PIN   35
#define SOUND_PIN     33
#define TASTER_PIN    32
#define VIB_PIN       4
#define SD_CS         5
#define NP_PIN        13
#define NUM_LEDS      11

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
RTC_DS3231 rtc;
SensirionI2cSen66 sen66;
Adafruit_NeoPixel ring(NUM_LEDS, NP_PIN, NEO_GRB + NEO_KHZ800);

bool senAvailable = false;
float pm2_5 = -1.0, pm1 = -1, pm4 = -1, pm10 = -1;
float voc = -1, nox = -1, temp = -1, hum = -1;
uint16_t devStatus = 0;

bool sdAvailable = false;
String serialStr = "-";

const float V_FULL_ADC  = 1.50; // entspricht 3.75V Batteriespannung
const float V_EMPTY_ADC = 1.10; // entspricht 2.75V Batteriespannung
float emaRaw = 0.0f;
const float ALPHA = 0.001f;
float dbSmoothed = 0;

const char* activityList[][2] = {
  {"WIG", "Alu"}, {"WIG", "Stahl"}, {"WIG", "CrNiSt"},
  {"MAG", ""}, {"MIG", "Alu"}, {"MIG", "CrNiSt"},
  {"Laserschw.", "Alu"}, {"Laserschw.", "Stahl"}, {"Laserschw.", "CrNiSt"},
  {"Lichtbogen", "Handschw."}, {"Schleifen", "grob"}, {"Rutschen", "fein"},
  {"Reinigen", "Loesungsm."}, {"Laser-", "schneiden"}, {"Plasma-", "schneiden"}, {"Schneid-", "brennen"}
};
uint8_t selectedActivity = 0;
bool inSelectionMode = false;
bool blinkState = true;
unsigned long lastBlink = 0;
unsigned long lastDbUpdate = 0;
unsigned long lastSensorUpdate = 0;
unsigned long lastLog = 0;
unsigned long startTime = 0;

unsigned long lastDebounceTime = 0;
const uint16_t DEBOUNCE_MS = 30;
bool lastButtonState = HIGH;
bool currentButtonState = HIGH;
bool buttonPressed = false;
bool longPressHandled = false;
unsigned long lastButtonDown = 0;

enum LuftQualitaetsZustand { GRUEN, ORANGE, ROT };
const float GRENZE_PM25_ORANGE = 625.0;
const float GRENZE_PM25_ROT = 1250.0;

bool vibroQuittiert = false;
unsigned long vibroQuittiertZeitpunkt = 0;
const unsigned long VIB_QUITTIER_TIMEOUT = 5UL * 60UL * 1000UL;

LuftQualitaetsZustand getLuftZustand(float pm) {
  if (pm < 0) return GRUEN;
  if (pm <= GRENZE_PM25_ORANGE) return GRUEN;
  if (pm <= GRENZE_PM25_ROT) return ORANGE;
  return ROT;
}

void setup() {
  Serial.begin(115200);
  pinMode(TASTER_PIN, INPUT_PULLUP);
  pinMode(VIB_PIN, OUTPUT);
  pinMode(16, OUTPUT);
  digitalWrite(16, HIGH);

  ring.begin();
  ring.setBrightness(128);
  ring.show();

  analogReadResolution(12);
  analogSetPinAttenuation(BATTERY_PIN, ADC_11db);
  analogSetPinAttenuation(SOUND_PIN, ADC_11db);
  emaRaw = analogRead(BATTERY_PIN);

  Wire.begin(21, 22);
  display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR);
  display.clearDisplay();
  rtc.begin();
  if (rtc.lostPower()) rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));

  if (sdAvailable) {
    if (!SD.exists("/data")) {
      SD.mkdir("/data");
    }
  }

  sen66.begin(Wire, 0x6B);
  uint16_t err = sen66.deviceReset();
  delay(1000);
  err |= sen66.startContinuousMeasurement();
  if (!err) {
    senAvailable = true;
    int8_t serialRaw[32] = "-";
    if (sen66.getSerialNumber(serialRaw, sizeof(serialRaw)) == 0) {
      serialStr = String((char*)serialRaw);
    }
  }

  sdAvailable = SD.begin(SD_CS);
  if (sdAvailable && !SD.exists("/data/data.csv")) {
    File f = SD.open("/data/data.csv", FILE_WRITE);
    if (f) {
      f.println("Zeit,Seriennummer,DeviceStatus,Kritisch,Aktivitaet,AkkuVolt,AkkuProzent,PM1.0,PM2.5,PM4.0,PM10.0,VOC,NOx,Temperatur,Feuchte,Lautstaerke_dB");
      f.close();
    }
  }

  startTime = millis();
}

void loop() {
  DateTime now = rtc.now();
  updateBattery();
  updateDB();
  updateSensor();
  handleButton();
  if (millis() - lastLog >= 1000) {
    logToSD(now);
    lastLog = millis();
  }
  updateDisplay(now);
  updateLEDs();
  updateBuzzer();
  updateVibration();
  checkVibroTimeout();
}

void updateBattery() {
  uint16_t raw = analogRead(BATTERY_PIN);
  emaRaw = ALPHA * raw + (1.0f - ALPHA) * emaRaw;
}

void updateDB() {
  if (millis() - lastDbUpdate >= 500) {
    int raw = analogRead(SOUND_PIN);
    float voltage = raw * (3.3f / 4095.0f);
    dbSmoothed = (voltage - 0.6f) * 50.0f + 30.0f;
    dbSmoothed = constrain(dbSmoothed, 0, 120);
    lastDbUpdate = millis();
  }
}

void updateSensor() {
  if (!senAvailable || millis() - lastSensorUpdate < 1000) return;
  bool ready = false; uint8_t dummy;
  sen66.getDataReady(dummy, ready);
  if (!ready) return;
  uint16_t err = sen66.readMeasuredValues(pm1, pm2_5, pm4, pm10, hum, temp, voc, nox, devStatus);
  if (err) pm2_5 = -1.0;
  lastSensorUpdate = millis();
}

void logToSD(DateTime now) {
  if (!sdAvailable) return;
  float vPin = emaRaw * (3.3f / 4095.0f);
  float soc = (vPin - V_EMPTY_ADC) / (V_FULL_ADC - V_EMPTY_ADC) * 100.0f;
  soc = constrain(soc, 0.0f, 100.0f);
  bool kritisch = devStatus > 0;
  String timestamp = String(now.timestamp(DateTime::TIMESTAMP_FULL));
  String activity = String(activityList[selectedActivity][0]) +
                    (strlen(activityList[selectedActivity][1]) > 0 ? "/" + String(activityList[selectedActivity][1]) : "");

  File file = SD.open("/data/data.csv", FILE_APPEND);
  if (file) {
    file.printf("%s,%s,0x%04X,%s,%s,%.3f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%.0f\n",
      timestamp.c_str(), serialStr.c_str(), devStatus,
      kritisch ? "ja" : "nein", activity.c_str(),
      vPin, soc, pm1, pm2_5, pm4, pm10, voc, nox, temp, hum, dbSmoothed);
    file.close();
  } else {
    sdAvailable = false;
  }
}

void handleButton() {
  int reading = digitalRead(TASTER_PIN);
  if (reading != lastButtonState) lastDebounceTime = millis();
  if ((millis() - lastDebounceTime) > DEBOUNCE_MS) {
    if (reading != currentButtonState) {
      currentButtonState = reading;
      if (currentButtonState == LOW) {
        lastButtonDown = millis();
        buttonPressed = true;
        longPressHandled = false;
      } else if (buttonPressed) {
        if (!longPressHandled && (millis() - lastButtonDown < 600)) {
          if (inSelectionMode) {
            selectedActivity = (selectedActivity + 1) % (sizeof(activityList) / sizeof(activityList[0]));
          }
          if (getLuftZustand(pm2_5) == ROT) {
            vibroQuittiert = true;
            vibroQuittiertZeitpunkt = millis();
          }
        }
        buttonPressed = false;
      }
    }
  }
  if (buttonPressed && !longPressHandled && (millis() - lastButtonDown >= 600)) {
    inSelectionMode = !inSelectionMode;
    triggerVibration(50);
    longPressHandled = true;
  }
  lastButtonState = reading;
}

void triggerVibration(uint16_t durationMs) {
  digitalWrite(VIB_PIN, HIGH);
  delay(durationMs);
  digitalWrite(VIB_PIN, LOW);
}

void updateDisplay(DateTime now) {
  float vPin = emaRaw * (3.3f / 4095.0f);
  float soc = (vPin - V_EMPTY_ADC) / (V_FULL_ADC - V_EMPTY_ADC) * 100.0f;
  soc = constrain(soc, 0.0f, 100.0f);

  if (millis() - lastBlink > (blinkState ? 750 : 250)) {
    blinkState = !blinkState;
    lastBlink = millis();
  }

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);

  display.setCursor(0, 0);
  if (blinkState) display.printf("%02d:%02d", now.hour(), now.minute());
  else display.printf("%02d %02d", now.hour(), now.minute());

  display.setCursor(50, 0);
  display.printf("%2.0f dB", dbSmoothed);

  display.setCursor(100, 0);
  display.printf("%3.0f%%", soc);

  display.setCursor(0, 12);
  if (pm2_5 >= 0) display.printf("PM2.5: %.0f ug/m3", pm2_5);
  else display.printf("PM2.5: - ug/m3");

  if (!inSelectionMode || (inSelectionMode && blinkState)) {
    display.setTextSize(2);
    int16_t x1, y1; uint16_t w, h;
    display.getTextBounds(activityList[selectedActivity][0], 0, 0, &x1, &y1, &w, &h);
    display.setCursor((SCREEN_WIDTH - w) / 2, 28);
    display.print(activityList[selectedActivity][0]);
    if (strlen(activityList[selectedActivity][1]) > 0) {
      display.getTextBounds(activityList[selectedActivity][1], 0, 0, &x1, &y1, &w, &h);
      display.setCursor((SCREEN_WIDTH - w) / 2, 48);
      display.print(activityList[selectedActivity][1]);
    }
  }

  display.display();
}

void updateLEDs() {
  if (!senAvailable || pm2_5 < 0 || millis() - startTime < 2500) {
    ring.fill(ring.Color(0, 0, 0), 0, NUM_LEDS);
    ring.show();
    return;
  }
  LuftQualitaetsZustand zustand = getLuftZustand(pm2_5);
  uint32_t color = 0;
  switch (zustand) {
    case GRUEN:  color = ring.Color(0, 255, 0); break;
    case ORANGE: color = ring.Color(255, 80, 0); break;
    case ROT:    color = ring.Color(255, 0, 0); break;
  }
  ring.fill(color, 0, NUM_LEDS);
  ring.show();
}

void updateBuzzer() {
  static unsigned long lastBuzz = 0;
  static bool buzzState = false;
  unsigned long now = millis();
  if (millis() - startTime < 2500) {
    digitalWrite(16, HIGH);
    return;
  }
  LuftQualitaetsZustand zustand = getLuftZustand(pm2_5);
  switch (zustand) {
    case ROT:
      if (now - lastBuzz >= 166) {
        buzzState = !buzzState;
        digitalWrite(16, buzzState ? LOW : HIGH);
        lastBuzz = now;
      }
      break;
    case ORANGE:
      if (now - lastBuzz >= 500) {
        buzzState = !buzzState;
        digitalWrite(16, buzzState ? LOW : HIGH);
        lastBuzz = now;
      }
      break;
    default:
      digitalWrite(16, HIGH);
      break;
  }
}

void updateVibration() {
  static unsigned long lastVib = 0;
  static bool vibState = false;
  if (vibroQuittiert || millis() - startTime < 2500) {
    digitalWrite(VIB_PIN, LOW);
    return;
  }
  LuftQualitaetsZustand zustand = getLuftZustand(pm2_5);
  if (zustand != ROT) {
    digitalWrite(VIB_PIN, LOW);
    return;
  }
  if (millis() - lastVib >= 300) {
    vibState = !vibState;
    digitalWrite(VIB_PIN, vibState);
    lastVib = millis();
  }
}

void checkVibroTimeout() {
  if (vibroQuittiert && millis() - vibroQuittiertZeitpunkt > VIB_QUITTIER_TIMEOUT) {
    vibroQuittiert = false;
  }
}