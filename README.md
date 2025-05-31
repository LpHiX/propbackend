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
sudo apt install git -y
```

3. UART
Enable uart in raspconfig, interfaces > serial > shell=no, port=yes
```
sudo raspi-config
```
Then, add this to the config by running the commands
```
sudo nano /boot/firmware/config.txt
```
For raspberry pi 5:
```
enable_uart=1
dtoverlay=disable-bt
dtoverlay=uart0,txd0_pin=14,rxd0_pin=15
dtoverlay=uart1,txd1_pin=0,rxd1_pin=1
```
For raspberry pi 4:
```
enable_uart=1
dtoverlay=disable-bt 
dtoverlay=uart1
dtoverlay=uart2
dtoverlay=uart3
dtoverlay=uart4
dtoverlay=uart5
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
Connect the data USB:
1. First check if has been connected.
```
lsblk
```
If sda1 is in there, that is probably the USB.
2. Find the UUID and have it automount on startup:
```
sudo blkid /dev/sda1
```
Should output
```
/dev/sda1: LABEL="PROPPI_DATA" UUID="3cfcaf06-1f4a-4777-bd37-60099bb45de7" BLOCK_SIZE="4096" TYPE="ext4" PARTUUID="bf495fd2-01"
```
3. Now put this into the file system table:
```
sudo nano /etc/fstab
```
Then add in:
```
UUID=3cfcaf06-1f4a-4777-bd37-60099bb45de7 /mnt/proppi_data ext4 defaults,nofail 0 0
```
At the last line.
4. Add this mounting point, reload the configuration then check if it has been mounted
```
sudo mkdir -p /mnt/proppi_data
sudo systemctl daemon-reload
lsblk
```
Disable the ethernet connection dropping randomly by setting a static IP for the raspberry pi:
```
sudo nano /etc/dhcpcd.conf
```
Then add this to the bottom (can be empty on a new PI)
```
interface eth0
static ip_address=192.168.137.2/24
static routers=192.168.137.1
static domain_name_servers=1.1.1.1
```
To upload to git private repos:
```
ssh-keygen -t ed25519 -C "you@example.com"
cat ~/.ssh/id_ed25519.pub
```
Then copy that into the github https://github.com/settings/keys
Then you are done!
Remember that you can only use SSH URLS:
HTTPS: https://github.com/LpHiX/propbackend
SSH: git@github.com:LpHiX/propbackend.git
