# proppibackend
Welcome to propbackend!


Ethernet Setup:
1. Check ICS connection. (Without internet the ethernet connection shuts down after around 2 minutes and you have to replug)
```
ping c -4 8.8.8.8
```
- If no ICS, disable and renable ICS on windows (Control Panel > Network and Sharing Center > Wifi > Sharing > Properties > Allow other network users to connect through this computer's internet connection)

2. Update (Checks for updates) and upgrade (Performs the list of upgrades from updates)
```
sudo apt update
sudo apt upgrade -y
```

3. UART
Enable uart in raspconfig
```
sudo raspi-config
```
- GND with UART device must be common
- Pinouts at https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio
```
           TXD    PIN  |  RXD      PIN  |  Communication Port
uart1 :  GPIO 14    8  |  GPIO 15   10  |  /dev/ttyAMA0
uart2 :  GPIO 0    27  |  GPIO 1    28  |  /dev/ttyAMA2
uart3 :  GPIO 4     7  |  GPIO 5    29  |  /dev/ttyAMA3
uart4 :  GPIO 8    24  |  GPIO 9    21  |  /dev/ttyAMA4
uart5 :  GPIO 12   32  |  GPIO 13   33  |  /dev/ttyAMA5
```