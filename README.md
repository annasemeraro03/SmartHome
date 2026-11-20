# SmartHome – IoT Smart Home Management System

## Overview

SmartHome is an IoT-based smart home management system designed to monitor environmental conditions, manage household devices and automate climate control.

The platform connects physical IoT devices to a cloud-based infrastructure, providing real-time monitoring, remote actuator management and historical data visualization through a web interface.

The system supports multiple houses, each with independent users, rooms, sensor data and device configurations. It also introduces a cooperative approach to temperature management, allowing environmental conditions to be considered when managing heating and cooling systems.

## Features

### Real-time Monitoring
- Real-time acquisition of environmental data through MQTT.
- Temperature and CO₂ concentration monitoring for each room.
- Live visualization of sensor readings through the web dashboard.
- Integration with external weather data to retrieve outdoor conditions.

### Smart Actuator Management
- Remote management of:
  - Heating systems.
  - Air conditioning systems.
  - Windows.
- Manual and automatic operating modes.
- Automatic climate-control suggestions based on environmental conditions and room-specific configuration.
- Mutual-exclusion logic for actuator management.
- Periodic storage of actuator states for historical analysis.

### Cloud-based Data Management
- Centralized data storage using Supabase.
- Separate data management for each house.
- Historical storage of sensor measurements and actuator states.
- Configurable temperature ranges and CO₂ thresholds for individual rooms.

### Web Application
- User authentication and session management.
- Personalized dashboard with environmental information.
- Room management and monitoring.
- Historical data visualization and statistics.
- User settings and password management.
- Password recovery through email.
- Dedicated administrator interface for managing houses, rooms and users.

### Telegram Integration
- Telegram bot account linking.
- Automatic notifications when actuators change state in automatic mode.
- Commands to retrieve the current status of the house.
- Account disconnection and notification management.

## System Architecture

The system follows a cloud-based IoT architecture in which physical devices communicate with the backend through an MQTT broker.

The main components are:

- **IoT devices:** collect environmental measurements and interact with household actuators.
- **MQTT broker:** handles asynchronous communication between IoT devices and the backend.
- **Flask backend:** manages application logic, user requests, sensor data and actuator commands.
- **Supabase:** provides cloud database services for storing users, houses, rooms, sensor measurements and actuator states.
- **Web interface:** allows users to monitor and manage their smart homes.
- **Telegram bot:** provides remote status information and automatic notifications.

### Architecture Overview

```text
       IoT Sensors and Actuators
                  |
                  | MQTT
                  |
            MQTT Broker
                  |
                  |
          Flask Backend
           /     |     \
          /      |      \
         /       |       \
    Supabase   Web UI   Telegram Bot
    Database  Dashboard Notifications
```

## Technologies

| Technology | Purpose |
|---|---|
| Python | Backend development and application logic |
| Flask | Web application and REST endpoints |
| MQTT | Communication between IoT devices and backend |
| Eclipse Paho MQTT | MQTT client implementation |
| Supabase | Cloud database and data persistence |
| PostgreSQL | Relational database |
| HTML / CSS / JavaScript | Web interface |
| Telegram Bot API | Notifications and remote status |
| Flask-Mail | Email services |
| OpenWeather API | External weather information |

## MQTT Communication

MQTT is used as the communication protocol between IoT devices and the backend.

The project uses the following topic structure:

**Sensor data**

```text
smarthome/house/{house_id}/{room}/sensors
```

Example:

```text
smarthome/house/1/kitchen/sensors
```

Example JSON payload:

```json
{
    "temperature": 22.5,
    "CO2": 850,
    "pressure": 1013.2
}
```

**Actuator data**

```text
smarthome/house/{house_id}/{room}/actuators
```

Example:

```text
smarthome/house/1/livingroom/actuators
```

Example JSON payload:

```json
{
    "heating": false,
    "conditioner": true,
    "windows": false
}
```

## Project Structure

```text
smartHome/
│
├── app.py
├── start.sh
├── requirements.txt
│
├── generazione_dati/
│   ├── sensors.py
│   └── devices.py
│
├── static/
│   ├── css/
│   ├── js/
│   └── logo.png
│
├── templates/
│
└── README.md
```

- `app.py`: main Flask application, including backend logic, MQTT communication, database integration and Telegram bot management.
- `start.sh`: script for creating the Python virtual environment, installing dependencies and starting the Flask server.
- `generazione_dati/sensors.py`: MQTT simulator for generating environmental sensor measurements.
- `generazione_dati/devices.py`: MQTT simulator for generating actuator states.
- `static/`: frontend resources, including stylesheets, JavaScript files and images.
- `templates/`: HTML templates used by the Flask application.

## Installation and Setup

### Prerequisites

- Python 3.
- pip.
- A Supabase project.
- An MQTT broker.
- API credentials for the external services used by the application.

### 1. Clone the repository

```bash
git clone <repository-url>
cd smartHome
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
```

Activate it:

**Linux / macOS**

```bash
source venv/bin/activate
```

**Windows**

```bash
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment variables

Configure the Supabase connection and the credentials required by the external services.

Sensitive information, including API keys, database credentials, email credentials and Telegram bot tokens, must be stored in environment variables rather than committed to the repository.

Create a `.env` file containing the required configuration, and ensure that it is included in `.gitignore`.

### 5. Start the application

On Linux:

```bash
chmod +x start.sh
./start.sh
```

Alternatively, start Flask manually:

```bash
flask --app app run --host=0.0.0.0 --port=5000
```

The application will be available at:

```text
http://localhost:5000
```

## Data Simulation

The project includes two Python scripts for testing MQTT communication without requiring physical IoT devices.

**Simulate environmental sensors**

```bash
python generazione_dati/sensors.py
```

Publishes simulated temperature, CO₂ and atmospheric pressure measurements every five seconds.

**Simulate actuator states**

```bash
python generazione_dati/devices.py
```

Publishes randomly generated heating, air conditioning and window states every five seconds.

Both simulators use the configured MQTT broker and topics.

## Future Improvements

Potential extensions include:

- Integration with additional IoT sensors and actuators.
- Improved automatic climate-control algorithms.
- Enhanced energy-efficiency monitoring.
- More advanced cooperation between multiple smart homes.
- Additional security mechanisms for IoT communication.
- Extended historical analytics and data visualization.

## Authors

Developed as an academic IoT project.