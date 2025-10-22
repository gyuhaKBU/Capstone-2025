#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <math.h>  // lroundf 사용

#define DHTTYPE DHT11
#define DHTPIN  27
DHT dht(DHTPIN, DHTTYPE);

LiquidCrystal_I2C lcd(0x27, 16, 2);



void setup() {
  Wire.begin(21, 22);          // 중요
  delay(100);
  dht.begin();
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0,0);
  lcd.print("Hello, ESP32!");
  delay(1000);
}
void loop() {
  float tf = dht.readTemperature();
  float hf = dht.readHumidity();

  if (isnan(tf) || isnan(hf)) {
    lcd.clear();
    lcd.print("DHT read error");
    return;
  }

  int t = (int)lroundf(tf);   // 반올림 → int
  int h = (int)lroundf(hf);

  lcd.clear();                 // 필요시에만 호출
  lcd.setCursor(0, 0);
  lcd.print("TEMP: ");
  lcd.print(t);
  lcd.print((char)223);        // '°'
  lcd.print("C");

  lcd.setCursor(0, 1);
  lcd.print("HUM : ");
  lcd.print(h);
  lcd.print("%");
  delay(1000);
}
