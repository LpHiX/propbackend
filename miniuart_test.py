import serial
import time
import json

# Configure the serial port
uart = serial.Serial(
# Default UART pins on Raspberry Pi: GPIO14 (TX) and GPIO15 (RX)
    port='/dev/ttyAMA5',  # Primary UART on Raspberry Pi 4
    baudrate=115200,      # Standard baud rate, adjust if needed
    timeout=1
)
try:
    print("Starting UART transmission. Press CTRL+C to stop.")
    
    while True:
        # Send "hello world" through UART
        message = "Test"
        uart.write(message.encode())
        print(f"Sent: {message.strip()}")
        time.sleep(0.1)
        # # Read reply from UART
        if uart.in_waiting > 0:
            reply = uart.readline().decode('utf-8').strip()
            print(f"Received: {reply}")
        

        
except KeyboardInterrupt:
    # Handle graceful exit on CTRL+C
    print("\nUART transmission stopped by user")
    
except Exception as e:
    # Handle other exceptions
    print(f"An error occurred: {e}")
    
finally:
    # Clean up and close the UART connection
    if uart.is_open:
        uart.close()
        print("UART connection closed")
