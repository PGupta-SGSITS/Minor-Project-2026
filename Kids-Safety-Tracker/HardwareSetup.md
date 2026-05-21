# Hardware Setup

![Hardware Setup](01_Project_Hardware_Setup.jpeg)

The hardware setup of the Kids Safety Tracker consists of multiple electronic components connected together to create a real-time child safety and emergency alert system.

The entire system is controlled by the ESP32 microcontroller, which acts as the brain of the project. It communicates with the GPS module, GSM module, SOS button, and Firebase cloud database to perform tracking and emergency alert operations.

---

## 1. ESP32 Dev Module

The ESP32 is the main controller of the system.

### Functions of ESP32

- Reads GPS coordinates from the NEO-6M GPS module
- Communicates with the SIM800L GSM module
- Detects SOS button presses
- Connects to WiFi
- Uploads location data to Firebase Realtime Database
- Controls SMS and calling operations

### Why ESP32 is used

- Built-in WiFi support
- Multiple UART serial ports
- Fast processing speed
- Low power consumption
- Suitable for IoT applications

### In this project

- UART2 is used for GPS communication
- UART1 is used for GSM communication

---

## 2. NEO-6M GPS Module

The NEO-6M GPS module is responsible for obtaining the real-time location of the child.

### Functions

- Receives satellite signals
- Calculates latitude and longitude
- Sends GPS data to ESP32

### Working

- GPS continuously searches for satellites
- Once a valid GPS fix is obtained, coordinates are generated
- ESP32 reads these coordinates using TinyGPSPlus library
- A Google Maps link is created using latitude and longitude

### Example

```text
https://www.google.com/maps?q=22.749500,75.846000
```

### Connections

- GPS TX → ESP32 GPIO16
- GPS RX → ESP32 GPIO17

---

## 3. SIM800L GSM Module

The SIM800L GSM module provides GSM communication capabilities.

### Functions

- Sends emergency SMS alerts
- Makes automatic emergency calls
- Receives SMS commands like `LOC`

### Working

- ESP32 sends AT commands to SIM800L
- GSM module communicates through cellular network
- SMS with Google Maps location is delivered to parent phone

### Emergency Process

1. SOS button pressed
2. ESP32 fetches GPS location
3. SMS sent to parent
4. Automatic call initiated

### Connections

- GSM TXD → ESP32 GPIO26
- GSM RXD → ESP32 GPIO27

---

## 4. SOS Push Button

The SOS button is used by the child during emergencies.

### Functions

- Triggers emergency alert sequence
- Sends location instantly to parent

### Working

- One side connected to GPIO14
- Other side connected to GND
- Uses INPUT_PULLUP configuration
- Normally reads HIGH
- Becomes LOW when pressed

### When pressed

- GPS location fetched
- SMS sent
- Call placed automatically

---

## 5. 18650 Battery

The 18650 lithium-ion battery powers the portable system.

### Functions

- Supplies power to GSM module
- Makes device portable
- Allows operation without external power source

### Importance

- SIM800L requires stable high current
- Battery provides sufficient current during SMS/call transmission

### Battery Specifications

- 3.7V rechargeable lithium-ion battery
- Portable and lightweight

---

## 6. Capacitor for Voltage Stabilization

A capacitor is connected across the GSM power supply.

### Purpose

- Stabilizes voltage during GSM transmission
- Prevents sudden voltage drops
- Avoids ESP32 restart problems

### Why needed

SIM800L draws high current spikes during:

- SMS sending
- Calling
- Network registration

### Without capacitor

- ESP32 may restart
- GSM module may fail

### Typical capacitor

- 1000µF electrolytic capacitor

---

## 7. Working of Complete Hardware System

### Step 1: Power ON

- ESP32 initializes all modules
- GSM connects to mobile network
- GPS starts searching satellites
- WiFi connects to Firebase

### Step 2: GPS Tracking

- GPS module continuously sends coordinates
- ESP32 processes location data
- Firebase database updated

### Step 3: Emergency Trigger

When child presses SOS button:

- ESP32 detects button press
- GPS location fetched
- Emergency SMS generated
- Google Maps link created
- SMS sent to parent
- Automatic call placed

### Step 4: Remote Location Request

Parent sends:

```text
LOC
```

Device replies with:

- Current GPS coordinates
- Google Maps link

---

## Overall System Purpose

The hardware setup creates a low-cost, portable, real-time child safety device capable of:

- Emergency alerting
- Live location sharing
- Parent communication
- Cloud data storage

The system works even in low internet areas because GSM communication is used for emergency alerts.
