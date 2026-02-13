import paho.mqtt.client as mqtt
import json
import time
import random

# --- CONFIGURAZIONE ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
TOPIC_SENSORS = "smarthome/house/1/kitchen/sensors"

def simulate_gradual_increase():
    client = mqtt.Client()
    
    # Valori di partenza
    temp = 15.0
    co2 = 500
    pressure = 1013.0  # Valore standard in hPa
    
    # Incrementi per step (ogni 5 secondi)
    temp_step = 1    # Arriverà a 25°C in circa 25 step
    co2_step = 60      # Arriverà a 2000 ppm in circa 25 step

    try:
        print(f"Connessione a {MQTT_BROKER}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start()
        
        print("--- SIMULAZIONE INCREMENTALE COMPLETA AVVIATA ---")
        print(f"Target: Temp 25°C, CO2 2000ppm, Press variabile. Topic: {TOPIC_SENSORS}")

        while True:
            # Facciamo variare leggermente la pressione ad ogni invio (+/- 0.5 hPa)
            # per simulare la sensibilità del sensore
            pressure += random.uniform(-0.5, 0.5)
            # Manteniamo la pressione in un range realistico (990 - 1030)
            pressure = max(990, min(1030, pressure))

            # Creazione payload
            payload_data = {
                "temperature": round(temp, 2),
                "CO2": int(co2),
                "pressure": round(pressure, 1) # Pressione inclusa con un decimale
            }
            
            payload = json.dumps(payload_data)
            client.publish(TOPIC_SENSORS, payload)
            
            print(f"📡 Inviato: Temp={payload_data['temperature']}°C, "
                  f"CO2={payload_data['CO2']}ppm, "
                  f"Press={payload_data['pressure']}hPa")

            # Logica di incremento graduale per Temperatura
            if temp < 28.0:
                temp += temp_step
            else:
                temp = 15.0 
                print("🔄 Reset Temperatura")

            # Logica di incremento graduale per CO2
            if co2 < 2000:
                co2 += co2_step
            else:
                co2 = 500 
                print("🔄 Reset CO2")

            # Attesa di 5 secondi
            time.sleep(5)

    except KeyboardInterrupt:
        print("\nSimulazione terminata.")
    finally:
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    simulate_gradual_increase()