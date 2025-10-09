# Setting a static IP for the Raspberry Pi

```bash
$ sudo nmtui
- Select Edit a connection
- Select Wired connection 1

# under IPv4 CONFIGURATION change the following
IPv4 CONFIGURATION <Manual>
Addresses 192.168.1.2/24
Gateway 192.168.1.1
DNS servers 127.0.0.1
            192.168.1.1

- at the bottom press OK to apply it
- go back and back again to the terminal

# apply the configuration
$ sudo nmcli device reapply eth0
Connection successfully reapplied to device 'eth0'.

# check if the ip address changed to the new one
$ ip a
[lots of things before this]
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc pfifo_fast state UP group default qlen 1000
    link/ether 2c:cf:67:26:3a:c8 brd ff:ff:ff:ff:ff:ff
    inet 192.168.1.2/24 brd 192.168.1.255 scope global noprefixroute eth0
       valid_lft forever preferred_lft forever
    inet6 fe80::8666:5173:4094:dd64/64 scope link noprefixroute 
       valid_lft forever preferred_lft forever
[lots of things after this]
```