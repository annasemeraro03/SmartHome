import paho.mqtt.client as mqtt
import json
import random
import time

# --- CONFIGURAZIONE ---
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
# Il topic deve corrispondere a quello cercato dal tuo backend/frontend
TOPIC = "smarthome/house/1/livingroom/actuators"

def simulate_actuators():
    # Creazione client MQTT
    client = mqtt.Client()
    
    try:
        print(f"Connessione al broker: {MQTT_BROKER}...")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_start() # Avvia il loop in background
        
        print(f"Simulatore avviato. Pubblicazione su: {TOPIC}")
        print("Premi CTRL+C per fermare.")

        while True:
            # Generazione dati casuali (Booleani)
            data = {
                "heating": random.choice([True, False]),
                "conditioner": random.choice([True, False]),
                "windows": random.choice([True, False])
            }
            
            # Creazione del JSON payload
            payload = json.dumps(data)
            
            # Pubblicazione
            result = client.publish(TOPIC, payload)
            
            # Verifica invio
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"✅ Inviato: {payload}")
            else:
                print(f"❌ Errore nell'invio del messaggio")

            # Attendi 5 secondi prima del prossimo invio
            time.sleep(5)

    except KeyboardInterrupt:
        print("\nSimulazione interrotta dall'utente.")
    except Exception as e:
        print(f"Errore: {e}")
    finally:
        client.loop_stop()
        client.disconnect()
        print("Connessione chiusa.")

if __name__ == "__main__":
    simulate_actuators()