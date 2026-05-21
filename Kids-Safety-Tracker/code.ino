// ======================================================
// KIDS SAFETY TRACKER PROJECT
// ESP32 + GPS + GSM + FIREBASE
// ======================================================
// ================= LIBRARIES =================
#include <WiFi.h>
#include <FirebaseESP32.h>
#include <TinyGPSPlus.h>
// ======================================================
// WIFI DETAILS
// ======================================================
#define WIFI_SSID "YOUR_WIFI_NAME"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
// ======================================================
// FIREBASE DETAILS
// ======================================================
#define FIREBASE_HOST "kidssafetytracker2-default-rtdb.firebaseio.com"
#define FIREBASE_AUTH ""
// ======================================================
// GPS MODULE
// ======================================================
TinyGPSPlus gps;
HardwareSerial gpsSerial(2);
#define GPS_RX 16
#define GPS_TX 17
// ======================================================
// GSM MODULE
// ======================================================
HardwareSerial gsmSerial(1);
#define GSM_RX 26
#define GSM_TX 27
// ======================================================
// SOS BUTTON
// ======================================================
#define SOS_BUTTON 14
// ======================================================
// PARENT PHONE NUMBER
// ======================================================
String parentNumber = "+916263035858";
// ======================================================
// FIREBASE OBJECTS
// ======================================================
FirebaseData fbdo;
FirebaseConfig config;
FirebaseAuth auth;
// ======================================================
// GET CURRENT GPS LOCATION
// ======================================================
String getLocationLink() {
unsigned long start = millis();
while (millis() - start < 10000) {
while (gpsSerial.available()) {
gps.encode(gpsSerial.read());
}
if (gps.location.isValid()) {
float latitude = gps.location.lat();
float longitude = gps.location.lng();
String mapsLink =
"https://www.google.com/maps?q=" +
String(latitude, 6) + "," +
String(longitude, 6);
Firebase.setFloat(fbdo, "/Location/Latitude", latitude);
Firebase.setFloat(fbdo, "/Location/Longitude", longitude);
Firebase.setString(fbdo, "/Location/GoogleMaps", mapsLink);
return mapsLink;
}
}
return "Location not available";
}
// ======================================================
// SEND SMS
// ======================================================
void sendSMS(String message) {
Serial.println("Sending SMS...");
gsmSerial.println("AT");
delay(1000);
gsmSerial.println("AT+CMGF=1");
delay(1000);
gsmSerial.print("AT+CMGS=\"");
gsmSerial.print(parentNumber);
gsmSerial.println("\"");
delay(1000);
gsmSerial.print(message);
delay(500);
gsmSerial.write(26);
delay(5000);
Serial.println("SMS SENT");
}
// ======================================================
// MAKE CALL
// ======================================================
void makeCall() {
Serial.println("Calling Parent...");
gsmSerial.print("ATD");
gsmSerial.print(parentNumber);
gsmSerial.println(";");
delay(15000);
gsmSerial.println("ATH");
Serial.println("Call Ended");
}
// ======================================================
// SOS FUNCTION
// ======================================================
void handleSOS() {
Serial.println("SOS BUTTON PRESSED");
String locationLink = getLocationLink();
String sms =
"EMERGENCY! HELP NEEDED.\n\nLocation:\n" +
locationLink;
sendSMS(sms);
delay(3000);
makeCall();
}
// ======================================================
// SETUP
// ======================================================
void setup() {
Serial.begin(115200);
gpsSerial.begin(9600, SERIAL_8N1, GPS_RX, GPS_TX);
gsmSerial.begin(9600, SERIAL_8N1, GSM_RX, GSM_TX);
pinMode(SOS_BUTTON, INPUT_PULLUP);
Serial.println("Connecting WiFi...");
WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
while (WiFi.status() != WL_CONNECTED) {
Serial.print(".");
delay(500);
}
Serial.println("\nWiFi Connected");
config.host = FIREBASE_HOST;
Firebase.begin(&config, &auth);
Firebase.reconnectWiFi(true);
Serial.println("Firebase Connected");
gsmSerial.println("AT");
delay(1000);
gsmSerial.println("AT+CMGF=1");
delay(1000);
Serial.println("SYSTEM READY");
}
// ======================================================
// LOOP
// ======================================================
void loop() {
while (gpsSerial.available()) {
gps.encode(gpsSerial.read());
}
if (gps.location.isUpdated()) {
float latitude = gps.location.lat();
float longitude = gps.location.lng();
String mapsLink =
"https://www.google.com/maps?q=" +
String(latitude, 6) + "," +
String(longitude, 6);
Serial.println("========== GPS DATA ==========");
Serial.print("Latitude: ");
Serial.println(latitude, 6);
Serial.print("Longitude: ");
Serial.println(longitude, 6);
Serial.println(mapsLink);
Firebase.setFloat(fbdo, "/Location/Latitude", latitude);
Firebase.setFloat(fbdo, "/Location/Longitude", longitude);
Firebase.setString(fbdo, "/Location/GoogleMaps", mapsLink);
Serial.println("Uploaded to Firebase");
Serial.println("==============================");
}
if (digitalRead(SOS_BUTTON) == LOW) {
delay(500);
if (digitalRead(SOS_BUTTON) == LOW) {
handleSOS();
delay(5000);
}
}
}
