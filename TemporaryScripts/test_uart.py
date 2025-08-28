import serial
import time

# Set up serial port
ser = serial.Serial(
    port='/dev/ttyAMA4',  # Use 'serial0' for the default UART on Pi
    baudrate=9600,
    timeout=1
)

test_message = "Hello UART!\n"

try:
    # Give the serial port some time to settle
    time.sleep(2)
    print("Sending:", test_message.strip())
    ser.write(test_message.encode())

    # Read back the echoed message
    time.sleep(0.5)
    received = ser.read(ser.in_waiting).decode()
    print("Received:", received.strip())

    if received.strip() == test_message.strip():
        print("UART loopback test successful.")
    else:
        print("UART loopback test failed.")

except Exception as e:
    print("Error:", e)

finally:
    ser.close()