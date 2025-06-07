# udp_server.py
import socket

HOST = '127.0.0.1'
PORT = 65432

with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
    s.bind((HOST, PORT))
    print("UDP server listening...")
    while True:
        data, addr = s.recvfrom(1024)
        print("Received from", addr, ":", data.decode())
