# proppibackend

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
- Pin 8 is TX
- Pin 10 is RX
- Pinouts at https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio