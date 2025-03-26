import serial
import time
import json

# Configure the serial port
# Default UART pins on Raspberry Pi: GPIO14 (TX) and GPIO15 (RX)
uart = serial.Serial(
    port='/dev/ttyS0',  # Primary UART on Raspberry Pi 4
    baudrate=921600,      # Standard baud rate, adjust if needed
    timeout=1
)
try:
    print("Starting UART transmission. Press CTRL+C to stop.")
    
    while True:
        # Send "hello world" through UART
        with open('test.json', 'r') as f:
            message = f.read()
        uart.write(message.encode())
        #print(f"Sent: {message.strip()}")
        
        # Read reply from UART
        if uart.in_waiting > 0:
            reply = uart.readline().decode('utf-8').strip()
            print(f"Received: {reply}")
        
        # Wait for 5 seconds
        time.sleep(0.05)
        
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
