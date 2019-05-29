# Domoticz-WEMO-Plugin
WEMO Plugin for Domoticz home automation

Controls WEMO devices your network (on/off switches and WEMO Link LED Lights)

## Key Features

* Auto-detects devices on your network
* Supports group of Link LED Lights
* Supports Dimmer feature for Link LED Lights

## Installation

Python version 3.4 or higher required & Domoticz version 3.9446 or greater.

To install:
* Go in your Domoticz directory using a command line and open the plugins directory.
* Run: ```git clone https://github.com/guino/Domoticz-WEMO.git```
* Restart Domoticz.

## Updating

To update:
* Go in your Domoticz directory using a command line and open the plugins directory then the Domoticz-WEMO directory.
* Run: ```git pull```
* Restart Domoticz.

## Alternate Install/Update:

* Simply create a directory under domoticz/plugins directory like 'WEMO' and download/copy the plugin.py file into it.
* Restart Domoticz.

## Configuration

There's no plugin configuration required, the setup of your devices/groups/etc should be done with the WEMO app and this plugin will detect/use the same settings.

## Usage

In the web UI, navigate to the Hardware page. In the hardware dropdown there will be an entry called "WEMO".
Devices detected are created in the 'Devices' tab, to use them you need to click the green arrow icon and 'Add' them to Domoticz.

## Change log

| Version | Information|
| ----- | ---------- |
| 1.0.0 | Initial upload version |
