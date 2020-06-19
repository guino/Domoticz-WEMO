# Domoticz WEMO Plugin
#
# Author: Wagner Oliveira (wbbo@hotmail.com)
#
"""
<plugin key="BasePlug" name="WEMO" author="Wagner Oliveira" version="1.0.0" wikilink="http://www.domoticz.com/wiki/plugins/plugin.html" externallink="https://github.com/guino/Domoticz-WEMO">
    <description>
        <h2>WEMO Plugin</h2><br/>
        This plugin is meant to control WEMO devices (on/off switches and Link LED lights)
        <h3>Features</h3>
        <ul style="list-style-type:square">
            <li>Auto-detection of devices on network</li>
            <li>Link LED Dimmer control</li>
        </ul>
        <h3>Devices</h3>
        <ul style="list-style-type:square">
            <li>ON/OFF Switches - Allow control of ON/OFF state as well as reporting of current state</li>
            <li>Link LED Bulbs - Allow control of ON/OFF/DIMMER state as well as reporting of current state</li>
        </ul>
        <h3>Configuration</h3>
        There is no configuration required here. Devices can be renamed in Domoticz or you can rename them in the WEMO app and remove them from Domoticz so they are detected with a new name or layout.
    </description>
    <params>
        <param field="Mode6" label="Debug" width="150px">
            <options>
                <option label="None" value="0"  default="true" />
                <option label="Python Only" value="2"/>
                <option label="Basic Debugging" value="62"/>
                <option label="Basic+Messages" value="126"/>
                <option label="Connections Only" value="16"/>
                <option label="Connections+Python" value="18" default="true" />
                <option label="Connections+Queue" value="144"/>
                <option label="All" value="-1"/>
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
import threading
import socket
import html
import sys
import time
from httplib2 import Http

class BasePlugin:
    enabled = False
    # WEMOs detected in network (WEMO udn to IP:PORT location)
    wemos = {}

    def __init__(self):
        return

    def onStart(self):
        Domoticz.Log("WEMO plugin started")
        if Parameters["Mode6"] != "0":
            Domoticz.Debugging(int(Parameters["Mode6"]))
            DumpConfigToLog()
        # Mark all existing devices as off/timed out initially (until they are discovered)
        for u in Devices:
            UpdateDevice(u, 0, 'Off', True)
        # Create/Start update thread
        self.updateThread = threading.Thread(name="WEMOUpdateThread", target=BasePlugin.handleThread, args=(self,))
        self.updateThread.start()

    def onStop(self):
        Domoticz.Debug("onStop called")
        while (threading.active_count() > 1):
            time.sleep(1.0)

    def onConnect(self, Connection, Status, Description):
        Domoticz.Debug("onConnect called")

    def onMessage(self, Connection, Data):
        Domoticz.Debug("onMessage called")

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug("onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

        # Find the udn for the Domoticz unit number provided
        udn = ''
        # For each WEMO udn
        for wemoudn in self.wemos:
            # If no devices set for this udn, skip it
            if 'devices' not in self.wemos[wemoudn]:
                continue
            # If the device we want is in this WEMO, set udn for it
            if Devices[Unit].DeviceID in self.wemos[wemoudn]['devices']:
                udn = wemoudn

        # If we didn't find it, leave (probably disconnected at this time)
        if udn == '':
            Domoticz.Error('Command for DeviceID='+Devices[Unit].DeviceID+' udn='+udn+" but device is not available.")
            return

        Domoticz.Log('Sending command for DeviceID='+Devices[Unit].DeviceID+' udn='+udn)

        # If it's a Bridge (otherwise we assume it's an on/off device)
        if udn.startswith('uuid:Bridge-'):
            # Send command to Group/Device
            headers={ 'Content-type' : 'text/xml; charset="utf-8"', 'SOAPACTION' : '"urn:Belkin:service:bridge:1#SetDeviceStatus"' }
            data='<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:SetDeviceStatus xmlns:u="urn:Belkin:service:bridge:1"><DeviceStatusList>&lt;?xml version=&quot;1.0&quot; encoding=&quot;UTF-8&quot;?&gt;&lt;DeviceStatus&gt;&lt;DeviceID&gt;'+Devices[Unit].DeviceID+'&lt;/DeviceID&gt;&lt;CapabilityID&gt;10008&lt;/CapabilityID&gt;&lt;CapabilityValue&gt;'+('0' if Command == 'Off' else str(round(Level*2.55)) )+':0&lt;/CapabilityValue&gt;&lt;IsGroupAction&gt;'+('YES' if Devices[Unit].DeviceID in self.wemos[udn]['groupids'] else 'NO')+'&lt;/IsGroupAction&gt;&lt;/DeviceStatus&gt;</DeviceStatusList></u:SetDeviceStatus></s:Body></s:Envelope>'
            cmd = doPOST(self.wemos[udn]['location']+'/upnp/control/bridge1', data, headers)
            Domoticz.Debug("cmdresp="+cmd)
            # Now we have to poll the status to make sure the next poll has the updated information on it (WEMO glitch?)
            ids = str(self.wemos[udn]['devices']).replace('[', '').replace(']', '').replace('\'', '').replace(' ', '')
            headers={ 'Content-type' : 'text/xml; charset="utf-8"', 'SOAPACTION' : '"urn:Belkin:service:bridge:1#GetDeviceStatus"' }
            data='<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:GetDeviceStatus xmlns:u="urn:Belkin:service:bridge:1"><DeviceIDs>'+ids+'</DeviceIDs></u:GetDeviceStatus></s:Body></s:Envelope>'
            state = doPOST(self.wemos[udn]['location']+'/upnp/control/bridge1', data, headers)
            # If we got a response and no error IDs, update the device for quicker update
            if cmd != '' and getElements(cmd, 'ErrorDeviceIDs')[0] == '':
                UpdateDevice(Unit, 0 if Command == 'Off' else 2, str(Level), Devices[Unit].TimedOut)
        else:
            # Send command to request change in state and read/parse status response
            headers={ 'Content-type' : 'text/xml; charset="utf-8"', 'SOAPACTION' : '"urn:Belkin:service:basicevent:1#SetBinaryState"' }
            data='<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:SetBinaryState xmlns:u="urn:Belkin:service:basicevent:1"><BinaryState>'+('1' if Command == 'On' else '0')+'</BinaryState></u:SetBinaryState></s:Body></s:Envelope>'
            state = doPOST(self.wemos[udn]['location']+'/upnp/control/basicevent1', data, headers)
            if state != '':
                state = html.unescape(state)
                state = getElements(state, 'BinaryState')[0]
            # Update domoticz status (On/Off and Timed out or not)
            if state == '' or state == '0':
                UpdateDevice(Unit, 0, 'Off', state == '')
            if state == '1':
                UpdateDevice(Unit, 1, 'On', False)

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self, Connection):
        Domoticz.Debug("onDisconnect called")

    def onHeartbeat(self):
        Domoticz.Debug("onHeartbeat called")
        # Create/Start update thread
        self.updateThread = threading.Thread(name="WEMOUpdateThread", target=BasePlugin.handleThread, args=(self,))
        self.updateThread.start()

    # Separate thread looping ever 10 seconds searching for new WEMOs on network and updating their status
    def handleThread(self):
        try:
            Domoticz.Debug("Searching for WEMOs ...")

            # Discovery message
            discmsg = \
                'M-SEARCH * HTTP/1.1\r\n' \
                'HOST:239.255.255.250:1900\r\n' \
                'ST:upnp:rootdevice\r\n' \
                'MX:2\r\n' \
                'MAN:"ssdp:discover"\r\n' \
                '\r\n'

            # Set up discovery UDP socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.settimeout(2)

            # Send discovery message
            s.sendto(discmsg.encode() , ('239.255.255.250', 1900) )

            # Read discovery responses
            try:
                while True:
                    # Receive and decode bytes to string
                    data, addr = s.recvfrom(65507)
                    data = data.decode()
                    # Clean up loc an udn
                    loc = ''
                    udn = ''
                    for line in data.splitlines():
                        if line.startswith('LOCATION:') and line.endswith('/setup.xml'):
                            loc = line[9:len(line)-10].strip()
                            Domoticz.Debug('WEMO detected: '+loc)
                        if line.startswith('USN:') and line.endswith('::upnp:rootdevice'):
                            udn = line[4:len(line)-17].strip()
                        if loc != '' and udn != '':
                            if udn not in self.wemos:
                                self.wemos[udn] = { "location" : loc }
                            else:
                                self.wemos[udn]['location'] = loc
                            loc = ''
                            udn = ''
            except socket.timeout:
                pass

            # Update device statuses
            for udn in self.wemos:
                self.updateWEMO( udn )

        except Exception as err:
            Domoticz.Error("handleThread: "+str(err)+' line '+format(sys.exc_info()[-1].tb_lineno))

    # Update WEMO information for provided udn
    def updateWEMO(self, udn):
        try:
            Domoticz.Debug('Updating '+self.wemos[udn]['location']+' udn='+udn)

            # If Wemo Link Bridge
            if udn.startswith('uuid:Bridge-'):
                # Get LINK devices
                headers={ 'Content-type' : 'text/xml; charset="utf-8"', 'SOAPACTION' : '"urn:Belkin:service:bridge:1#GetEndDevices"' }
                data='<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:GetEndDevices xmlns:u="urn:Belkin:service:bridge:1"><ReqListType>SCAN_LIST</ReqListType><DevUDN>'+udn+'</DevUDN></u:GetEndDevices></s:Body></s:Envelope>'
                scan = doPOST(self.wemos[udn]['location']+'/upnp/control/bridge1', data, headers)
                scan = html.unescape(scan)

                # Split group information
                groupinfo = getElements(scan, 'GroupInfo')
                # Get Groups and their IDs
                groups = getElements(scan, 'GroupName')
                groupIDs = getElements(scan, 'GroupID')
                groupTimedOut = [False]*len(groups)
                groupdevs = [[]]*len(groups)
                allgroupdevs = []
                # Save group ids for this udn
                self.wemos[udn]['groupids'] = groupIDs
                # For each group
                for i in range(0, len(groups)):
                    Domoticz.Debug('grp='+groups[i]+' id='+groupIDs[i])
                    # See if it's already in Domoticz (and get unit # if so)
                    unit = getUnit(groupIDs[i])
                    # If it's not in Domoticz already
                    if unit == 0:
                        # Not in Domoticz yet, add it in the next available unit number
                        unit = nextUnit()
                        # Add device as a dimmer switch
                        Domoticz.Device(Name=groups[i], Unit=unit, Type=244, Subtype=73, Switchtype=7, Image=0, DeviceID=groupIDs[i]).Create()
                    # Get devices IDs associated with this group
                    groupdevs[i] = getElements(groupinfo[i], 'DeviceID')
                    Domoticz.Debug('groupdevs '+str(i)+'='+str(groupdevs[i]))
                    # Keep track of all devices that are pare of a group
                    allgroupdevs.extend(groupdevs[i])

                # Get Individual LED devices and their IDs
                leds = getElements(scan, 'FriendlyName')
                ledIDs = getElements(scan, 'DeviceID')
                for i in range(0, len(leds)):
                    Domoticz.Debug('led='+leds[i]+' id='+ledIDs[i])
                    # See if it's already in Domoticz (and get unit # if so)
                    unit = getUnit(ledIDs[i])
                    # If it's not in Domoticz already AND it is not part of a group
                    if unit == 0 and ledIDs[i] not in allgroupdevs:
                        # Not in Domoticz yet, add it in the next available unit number
                        unit = nextUnit()
                        # Add device as a dimmer switch
                        Domoticz.Device(Name=leds[i], Unit=unit, Type=244, Subtype=73, Switchtype=7, Image=0, DeviceID=ledIDs[i]).Create()

                # Initialize devices list if required
                if 'devices' not in self.wemos[udn]:
                    self.wemos[udn]['devices'] = []

                # Make sure all group and LED IDs are in the devices list
                self.wemos[udn]['devices'].extend( list( set(groupIDs)-set(self.wemos[udn]['devices']) ) )
                self.wemos[udn]['devices'].extend( list( set(ledIDs)-set(self.wemos[udn]['devices']) ) )

                # Get group+device status (all at once since ids is blank)
                ids = str(self.wemos[udn]['devices']).replace('[', '').replace(']', '').replace('\'', '').replace(' ', '')
                Domoticz.Debug("ids="+ids)
                headers={ 'Content-type' : 'text/xml; charset="utf-8"', 'SOAPACTION' : '"urn:Belkin:service:bridge:1#GetDeviceStatus"' }
                data='<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:GetDeviceStatus xmlns:u="urn:Belkin:service:bridge:1"><DeviceIDs>'+ids+'</DeviceIDs></u:GetDeviceStatus></s:Body></s:Envelope>'
                state = doPOST(self.wemos[udn]['location']+'/upnp/control/bridge1', data, headers)
                state = html.unescape(state)

                # For each device ID/State
                stateids = self.wemos[udn]['devices']
                states = getElements(state, 'CapabilityValue')
                for i in range(0, len(states)):
                    # Get level information (second , delimited state)
                    level = states[i].split(',')[1]
                    Domoticz.Debug('id='+stateids[i]+' level='+level)
                    # If this device isn't part of a group
                    if stateids[i] not in allgroupdevs and stateids[i] not in groupIDs:
                        unit = getUnit(stateids[i])
                        timedout = False
                        if level == '':
                            level = '0'
                            timedout = True
                        else:
                            level = level[0:level.rfind(':')]
                        level = str( round(int(level)/2.55) )
                        UpdateDevice(unit, 0 if states[i][0:1] == '0' else 2, level, timedout)
                    else:
                        # If it's disconnected
                        if level == '':
                            # Find group 'g' this ID belongs to
                            for g in range(0, len(groupIDs)):
                                if stateids[i] in groupdevs[g]:
                                    groupTimedOut[g] = True
                                    break;

                # For each group, update its device status
                states = getElements(state, 'CapabilityValue')
                for g in range(0, len(stateids)):
                    if stateids[g] in groupIDs:
                        level = states[g].split(',')[1]
                        level = level[0:level.rfind(':')]
                        level = str( (int(level)*100)//255 )
                        UpdateDevice(getUnit(stateids[g]), 0 if states[g][0:1] == '0' else 2, level, groupTimedOut[g])

            # On/Off switch
            else:
                # Get device ID
                devid = udn[udn.rfind('-')+1:]
                # Make sure devices list is updated
                self.wemos[udn]['devices'] = [ devid ]
                # See if it's already in Domoticz (and get unit # if so)
                unit = getUnit(devid)
                Domoticz.Debug('unit='+str(unit))
                # If it's not in Domoticz already
                if unit == 0:
                    # Add it in the next available unit number
                    unit = nextUnit()
                    # Assume it's an on/off device
                    name = 'Switch'
                    headers={ 'Content-type' : 'text/xml; charset="utf-8"', 'SOAPACTION' : '"urn:Belkin:service:basicevent:1#GetFriendlyName"' }
                    data='<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:GetFriendlyName xmlns:u="urn:Belkin:service:basicevent:1"><FriendlyName></FriendlyName></u:GetFriendlyName></s:Body></s:Envelope>'
                    scan = doPOST(self.wemos[udn]['location']+'/upnp/control/basicevent1', data, headers)
                    scan = html.unescape(scan)
                    name = getElements(scan, 'FriendlyName')[0]
                    Domoticz.Debug('name='+name)
                    Domoticz.Device(Name=name, Unit=unit, Type=244, Subtype=73, Switchtype=0, Image=9, DeviceID=devid).Create()
                # Get current status
                headers={ 'Content-type' : 'text/xml; charset="utf-8"', 'SOAPACTION' : '"urn:Belkin:service:basicevent:1#GetBinaryState"' }
                data='<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:GetBinaryState xmlns:u="urn:Belkin:service:basicevent:1"><BinaryState>1</BinaryState></u:GetBinaryState></s:Body></s:Envelope>'
                state = doPOST(self.wemos[udn]['location']+'/upnp/control/basicevent1', data, headers)
                if state != '':
                    state = html.unescape(state)
                    state = getElements(state, 'BinaryState')[0]
                Domoticz.Debug('state='+state)
                # Update domoticz status (On/Off and Timed out or not)
                if state == '' or state == '0':
                    UpdateDevice(unit, 0, 'Off', state == '')
                if state == '1':
                    UpdateDevice(unit, 1, 'On', False)

        except Exception as err:
            Domoticz.Error("updateWEMO: "+str(err)+' line '+format(sys.exc_info()[-1].tb_lineno))

global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()

    # Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return

# Basic XML Element reader without imports
def getElements(data, tag):
    elems = []
    start = 0
    start = data.find('<'+tag+'>', start)
    while start > 0:
        end = data.find('</'+tag+'>', start+len(tag))
        elems.append(data[start+len(tag)+2:end])
        start = data.find('<'+tag+'>', start+len(tag))
    return elems

# Simple POST method (used in separate thread to prevent Domoticz blocking)
def doPOST(url, data, headers):
    http = Http(cache=None, timeout=2.0)
    try:
        resp, content = http.request(uri=url, method='POST', headers=headers, body=data)
    except:
        return ''
    return content.decode('utf-8')

# Loop thru domoticz devices and see if there's a device with matching DeviceID, if so, return unit number, otherwise return zero
def getUnit(devid):
    unit = 0
    for x in Devices:
        if Devices[x].DeviceID == devid:
            unit = x
            break
    return unit

# Find the smallest unit number available to add a device in domoticz
def nextUnit():
    unit = 1
    while unit in Devices and unit < 255:
        unit = unit + 1
    return unit

def UpdateDevice(Unit, nValue, sValue, TimedOut):
    # Make sure that the Domoticz device still exists (they can be deleted) before updating it
    if (Unit in Devices):
        if (Devices[Unit].nValue != nValue) or (Devices[Unit].sValue != sValue) or (Devices[Unit].TimedOut != TimedOut):
            Devices[Unit].Update(nValue=nValue, sValue=str(sValue), TimedOut=TimedOut)
            Domoticz.Log("Update "+str(nValue)+":'"+str(sValue)+"' ("+Devices[Unit].Name+") TimedOut="+str(TimedOut))
    return
