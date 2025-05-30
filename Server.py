import socket
import json
import threading
import time
import sqlite3
from datetime import datetime, timedelta, date
from cryptography.hazmat.primitives import padding
import os
import math
import logging
import colorlog
from Debug import ResetSystem
from flask import Flask, jsonify, Response, request
from flask_cors import CORS
import csv  
from dotenv import load_dotenv, dotenv_values
import bcrypt

#!TEMP
if(input("SHOULD RESET FOLDERS (Y/N): ").strip().upper() == "Y"):
    ResetSystem.ClearFolders([r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Files To Send",r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Received Files", r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Files To Return"])

#!TEMP
if(os.path.exists(f"ServerGeneral.log")):
    os.remove("PeersP2PStorage.db")
    os.remove(f"ServerGeneral.log")
    os.remove(f"ServerErrors.log")
    
#Setting up .env
load_dotenv(dotenv_path=".env.server")
sslCertificateLocation = os.getenv("SSL_CERTIFICATE_LOCATION")

#No exc_info in logging
class NoStackTraceFormatter(logging.Formatter):
    def format(self, record):
        record.exc_info = None  # removes stack trace
        return super().format(record)

#Setting logging level right
loggingLevelDict = {
    "Info" : logging.INFO,
    "Warning" : logging.WARNING,
    "Error" : logging.ERROR
}

# Signaling server class
class SignalingServer:
    def __init__(self, host='0.0.0.0', port=12345):
        self.host = host
        self.port = port
        self.peers = {}
        self.lock = threading.Lock()  # Lock to ensure thread safety for shared data
        self.chartDataLock = threading.Lock()
        self.timeBetweenHeartbeats = 10
        self.spacePerPeerMB = 1024
        self.chunkSize = (64) * 1024 #Recommended to change the value in brackets - this changes the amount of KiB
        self.redundancyValue = 0
        self.connectedAddrs = []
        self.completedFileIDs = []
        self.storedRequestedFilesData = []
        self.timeBetweenReturns = 10
        self.runningHeartbeatCheck = False
        self.filesToDelete = []
        self.shuttingDown = False
        self.threads = []
        self.serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lastUsedFileID = None
        self.mainLoggingLevel = logging.INFO
        self.serverActive = False
        self.lastHourReading = None
        self.fileIDLock = threading.Lock()
        self.fileDeletionLock = threading.Lock()
        
        #.env
        self.filesToReturnLocation = os.getenv("SERVER_FILES_TO_RETURN_FOLDER_LOCATION")
        self.filesToSendLocation = os.getenv("SERVER_FILES_TO_SEND_FOLDER_LOCATION")
        self.frontendLogLocation = os.getenv("FRONTEND_LOG_LOCATION")
        self.peerDataCSVLocation = os.getenv("PEER_DATA_CSV_LOCATION")
        self.serverDataJSONLocation = os.getenv("SERVER_DATA_JSON_LOCATION")
        
        #*LOGGING
        # Create a colored formatter for console output
        self.logFormatter = colorlog.ColoredFormatter(
            "%(log_color)s%(levelname)s:%(reset)s %(message)s",
            log_colors={
                "DEBUG": "cyan",
                "INFO": "green",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )

        # Create a console handler
        self.consoleLogHandler = logging.StreamHandler()
        self.consoleLogHandler.setFormatter(self.logFormatter)

        # Frontend handler
        self.frontendLogHandler = logging.FileHandler(frontendLogLocation)
        self.frontendLogHandler.setFormatter(NoStackTraceFormatter("%(asctime)s - %(levelname)s - %(message)s"))
        self.frontendLogHandler.setLevel(self.mainLoggingLevel)  
        
        # General handler
        self.generalLogHandler = logging.FileHandler("ServerGeneral.log")
        self.generalLogHandler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        self.generalLogHandler.setLevel(logging.DEBUG) 

        # Create a file handler for "shared.log"
        self.errorLogHandler = logging.FileHandler("ServerErrors.log")
        self.errorLogHandler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        self.errorLogHandler.setLevel(logging.ERROR)  

        # Create a logger
        self.logger = logging.getLogger("colorLogger")
        self.logger.setLevel(logging.DEBUG)

        # Add handlers to the logger
        self.logger.addHandler(self.consoleLogHandler)  # Logs to console
        self.logger.addHandler(self.generalLogHandler)    
        self.logger.addHandler(self.errorLogHandler)     
        self.logger.addHandler(self.frontendLogHandler)       
    
    def Shutdown(self):
        self.shuttingDown = True
        
        self.logger.info("BEGINNING SHUTDOWN SEQUENCE")
        self.logger.info("CLOSING ALL THREADS")
        #Waiting for all threads to finish
        for t in self.threads:
            t.join()
    
        #Telling all users to finish
        self.logger.info("CLOSING ALL PEERS")
        for peer in self.peers:
            connectionSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            connectionSocket.connect((self.peers[peer]["ip"], self.peers[peer]["port"]))
            shutdownMessage = {"type" : "serverShutdown"}
            connectionSocket.send(json.dumps(shutdownMessage).encode())
            connectionSocket.close()
        
        
        #Closing server
        self.logger.info("SHUTTING SERVER. GOODBYE")
        self.serverSocket.close()
        self.serverActive = False
            
    def FillOldValues(self):
        with self.chartDataLock:
            with open(self.peerDataCSVLocation, "r") as fileHandle:
                lines = fileHandle.readlines()
            
            csvDatetimes = []
            for line in lines:
                line = line.strip("\n")
                lineTimestamp  = line.split(",")[0]
                lineHour = int(lineTimestamp.split("--")[0])
                lineDate = (lineTimestamp.split("--")[1]).split("-")
                lineDay = int(lineDate[0])
                lineMonth = int(lineDate[1])
                lineYear = int(lineDate[2])
                
                #csvDatetimes.append([datetime(hour=lineHour, day=lineDay,month=lineMonth,year=lineYear), line.split(",")[1]])

            #print(f"CSV : {csvDatetimes}")
            
            csvDatetimes.reverse()
            newLines = []
                
            lastTime = datetime.now().replace(minute=0, second=0, microsecond=0)
            i = 0
            while(len(newLines) < 720):
                if(i<len(csvDatetimes)) and (lastTime - csvDatetimes[i][0]) <= timedelta(hours=1):
                    #Correct setup
                    
                    newLines.append(csvDatetimes[i])
                    lastTime = csvDatetimes[i][0]
                    i+= 1
                else:
                    self.logger.debug(f"FILL OLD VALUES TIMEDELTA : {lastTime}, {timedelta(minutes=30) <= timedelta(hours=1)}")
                    newLines.append([lastTime,"0"])
                    lastTime -= timedelta(hours=1)
            
            #Formatting back into strings
            newLines.reverse()
            newLinesOutput = []
            for newLine in newLines:
                newLineDatetime = newLine[0]
                newLinesOutput.append(f"{newLineDatetime.hour}--{newLineDatetime.day}-{newLineDatetime.month}-{newLineDatetime.year},{newLine[1]}\n")
           
            newLinesOutput[719] = newLinesOutput[719].strip("\n") 
                          
            #Writing
            with open(self.peerDataCSVLocation, "w") as fileHandle:
                fileHandle.writelines(newLinesOutput)
                
            #print(newLinesOutput)
    
    def handle_peer(self, peer_socket):
        try:
            self.logger.debug("Waiting to receive peer info...")  # Debug message
            peer_info = peer_socket.recv(1024).decode()
            
            if not peer_info:
                self.logger.warning("No data received from peer, returning...")
                return

            self.logger.info(f"Received peer info: {peer_info}")  # Debug message
            peer_info = json.loads(peer_info)

            #Receiving files we need 
            databaseConnection = sqlite3.connect('PeersP2PStorage.db')
            cursor = databaseConnection.cursor()
            
            t = (threading.Thread(target= self.RequestFilesFromUser, args = (), daemon=True))
            t.start()
            self.threads.append(t)
            
            if("type" in peer_info):
                if(peer_info["type"] == "uploadPing"):
                    self.logger.info("ACCEPTING FILE")
                    self.AcceptFileFromPeer(peer_info["userCode"], peer_socket)
                elif(peer_info["type"] == "requestPing"):
                    self.logger.debug(f"FILE REQUEST FOR FILE {peer_info['fileID']}")
                    
                    #Add file to request list   
                    self.AddFileToRequestList(peer_info['fileID'])
                elif(peer_info["type"] == "deleteRequest"):
                    self.logger.debug(f"DELETE REQUEST FOR FILE {peer_info['fileID']}")
                    
                    #Add file to request list   
                    self.filesToDelete.append(peer_info['fileID'])
            else:
                peer_ip = peer_info['ip']
                peer_port = peer_info['port']
                peerUserCode = peer_info['userCode']
                self.logger.info(f"New peer connected: {peer_ip}:{peer_port}")

                # Store peer info in a thread-safe manner
                with self.lock:
                    self.peers[f"{peer_ip}:{peer_port}"] = peer_info

                #Sending the server info
                serverInfoMessage = {"chunkSize" : self.chunkSize}
                peer_socket.send(json.dumps(serverInfoMessage).encode().ljust(128, b"\0"))

                # Send the updated peers list to the connecting peer
                with self.lock:
                    peer_socket.send(json.dumps(self.peers).encode())

                self.logger.info(f"Current peers list: {self.peers}")  # Debug message
                
                #Try adding to the database
                try:
                    cursor.execute('''
                    INSERT INTO peers (ipAddress, port, userCode, availableSpace)
                    VALUES (?, ?, ?, ?)
                    ''', (peer_ip, peer_port, peerUserCode, self.spacePerPeerMB * 1024 * 1024))  #Converting into MiB to B
                    databaseConnection.commit()
                    self.logger.info("User commited to database")
                except sqlite3.IntegrityError as e:  # Catch IntegrityError specifically
                    self.logger.warning(f"Database Error: {e}")
                    self.logger.warning("User already in database")
                except Exception as e:  # Catch any other exceptions
                    self.logger.error(f"Unexpected Error: {e}", exc_info=True)
                finally:
                    databaseConnection.close()
        except Exception as e:
            self.logger.error(f"Error handling peer: {e}", exc_info=True)
        finally:
            peer_socket.close()
            
    def FileDeletor(self):
        try:
            while not self.shuttingDown:
                time.sleep(10)
                self.logger.debug("TRYING TO DELETE FILES")
                databaseConn = sqlite3.connect("PeersP2PStorage.db")
                cursor = databaseConn.cursor()
                
                #Checking if file is within our stored files
                with self.fileDeletionLock:
                    self.logger.debug(f"COMPLETEDFILEIDS : {self.completedFileIDs}")
                    for fileID in self.filesToDelete:
                        if(fileID in self.completedFileIDs):
                            #File is within our buffer of files to share
                            dirContents = os.listdir(self.filesToSendLocation)
                            for dirContent in dirContents:
                                if(fileID in dirContent):
                                    os.remove(self.filesToSendLocation + "/" + dirContent)
                                    break
                            self.completedFileIDs.remove(fileID)
                            self.logger.debug(f"DELETING {fileID} FROM FILESTOSEND")
                            
                            #Removing from everything else
                            self.filesToDelete.remove(fileID)
                            cursor.execute("DELETE FROM files WHERE fileID = ?", (fileID,))
                            databaseConn.commit()
                        
                
                placeHolders = ", ".join(["?"] * len(self.filesToDelete))
                cursor.execute(f"SELECT * FROM files WHERE fileID IN ({placeHolders})", tuple(self.filesToDelete))
                rows = cursor.fetchall()
                for row in rows:
                    fileID = row[0]
                    chunkLocations = json.loads(row[5])
                    
                    self.logger.debug(f"DELETING FILE {fileID}")
                    self.logger.debug(f"ROW : {row}, LOCATIONS : {chunkLocations}")
                    
                    for chunkIndex in chunkLocations[:]:
                        self.logger.debug(f"index is {chunkIndex['chunkIndex']}")
                        self.logger.debug(f"locations 1 {chunkIndex['userCodes']}")
                        locations = chunkIndex["userCodes"]
                        for location in locations[:]: #Making shallow copy
                            self.logger.debug(f"location is {location}")
                            self.logger.debug(f"locations 2 are {locations}")
                            userIP = location[0]
                            userPort = location[1]
                            if(f"{userIP}:{userPort}" in self.peers):
                                connectionSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                connectionSocket.connect((userIP,userPort)) 
                                fileDeleteSuccess = self.DeleteFile(fileID, userIP, userPort, connectionSocket, chunkIndex["chunkIndex"])
                                if(fileDeleteSuccess):
                                    if location[0] == userIP and location[1] == userPort:
                                        locations.remove(location)  
                                
                                connectionSocket.close()
                    
                        if(locations == []):
                            chunkLocations.remove(chunkIndex)
                            self.logger.debug(f"Removing index {chunkIndex['chunkIndex']}")
                
                    if(chunkLocations == []):
                        self.logger.debug("chunkLocations is clear")
                        #Removing from everything else
                        self.filesToDelete.remove(fileID)
                        cursor.execute("DELETE FROM files WHERE fileID = ?", (fileID,))
                        databaseConn.commit()

                #Update JSON
                UpdateJSON("Files To Delete",len(self.filesToDelete),self.serverDataJSONLocation , "ServerData")
                   
        except Exception as e:
            self.logger.error(f"Error {e} in FileDeletor", exc_info=True)
        

    def DeleteFile(self, fileID, userIP, userPort, connectionSocket, chunkIndex): 
        try:
            self.logger.debug(f"chunkIndex in DELETEFILE : {chunkIndex}")
            deleteMessage = {"type": "deleteFileServerRequest"}
            connectionSocket.send(json.dumps(deleteMessage).encode().ljust(64, b"\0"))
            
            response = json.loads(connectionSocket.recv(64).decode())
            if(response) and (response["type"] == "deleteFileServerRequestAccept"):
                infoMessage = {"fileID" : fileID, "chunkIndex" : chunkIndex}
                self.logger.debug(f"INFOMESSAGE : {infoMessage}")
                connectionSocket.send(json.dumps(infoMessage).encode().ljust(64, b"\0"))
                fileSizeRaw = connectionSocket.recv(32).decode()
                self.logger.debug(f"RAW SIZE IN DELETEFILE : {fileSizeRaw}")
                fileSizeDict = json.loads(fileSizeRaw)
            
                #Updating size on SQL
                databaseConn = sqlite3.connect("PeersP2PStorage.db")
                cursor = databaseConn.cursor()
                cursor.execute("SELECT * FROM peers WHERE ipAddress = ? AND port = ?",(userIP, userPort))
                row = cursor.fetchone()
                availableSpace = row[3] + fileSizeDict["size"]
                cursor.execute("UPDATE peers SET availableSpace = ? WHERE ipAddress = ? AND port = ?",(availableSpace, userIP, userPort))
                databaseConn.commit()
                databaseConn.close()
            
                return True #Success
            else:
                return False
        except Exception as e:
            self.logger.error(f"Error {e} in DeleteFile", exc_info=True)
            return False #Failure
        
    def RequestFilesFromUser(self):
        try:
            databaseConn = sqlite3.connect("PeersP2PStorage.db")
            cursor = databaseConn.cursor()
            cursor.execute("SELECT * FROM filesToRequest")
            rows = cursor.fetchall()
            for row in rows:
                self.RequestFileFromUser(row[0])
            databaseConn.close()
        except Exception as e:
            self.logger.error(f"Error {e} in RequestFilesFromUser" , exc_info=True)

    def RemoveFromPeers(self, ipPortCode):
        try:
            for peer in self.peers:
                if(peer == ipPortCode):
                    del self.peers[ipPortCode]
                    break
        except Exception as e:
            self.logger.error(f"Error {e} in RemoveFromPeers" , exc_info=True)

    def AddChunkToFile(self, fileName, chunkIndex, chunkData):
        try:
            with open(fileName, "r+b") as fileHandle:
                offset = chunkIndex * self.chunkSize
                fileHandle.seek(offset)
                fileHandle.write(chunkData)
        except Exception as e:
            self.logger.error(f"Error {e} in AddChunkToFile" , exc_info=True)

    def RequestFileFromUser(self, fileID):
        try:
            
            databaseConn = sqlite3.connect("PeersP2PStorage.db")
            self.logger.debug(f"REQUESTING FILE {fileID}")
            cursor = databaseConn.cursor()
            cursor.execute("SELECT * FROM files WHERE fileID = ?", (fileID,))
            row = cursor.fetchone()
            
            ownerUserCode = row[1]
            chunkLocations = json.loads(row[5])
            
            self.logger.debug(f"chunkLocations RFFU : {chunkLocations}")
            
            cursor.execute("SELECT * FROM filesToRequest WHERE fileID = ?", (fileID,))
            row = cursor.fetchone()
            downloadedChunks = set(json.loads(row[1]))
            chunkCount = int(row[2])
            fileStorageName = row[3]
            
            #Requesting chunks
            for chunkLocation in chunkLocations:
                chunkIndex = chunkLocation["chunkIndex"]
                userCodes = chunkLocation["userCodes"]

                user = None
                
                if(chunkIndex in downloadedChunks):
                    continue
                
                for userCode in userCodes:
                    #Checking if user is online
                    
                    self.logger.debug(f"CURRENT USER CODE : {userCode} | {userCode[2]}")
                        
                    for peer in self.peers:
                        if(self.peers[peer]["userCode"] == userCode[2]):
                            #They are online
                            user = userCode[2]
                            break
                            
                   
                if(user != None):
                    #Request chunk from user
                    self.logger.debug(f"{user} is user")
                    chunkData = self.RequestChunkFromUser(user, fileID, chunkIndex, ownerUserCode)
                    
                    #self.logger.debug(f"OUTPUT OF RequestFileFromUser : {chunkData.decode()}")    
                    
                    self.AddChunkToFile(fileStorageName,chunkIndex,chunkData)
                    downloadedChunks.add(chunkIndex)
            
            if(len(downloadedChunks) == chunkCount):
                #Complete
                cursor.execute("DELETE FROM filesToRequest WHERE fileID = ?", (fileID,))
                cursor.execute("INSERT INTO filesToReturn (fileID, ownerUserCode) VALUES (?, ?)", (fileID,ownerUserCode))
                databaseConn.commit()
                
                
            else:
                cursor.execute("UPDATE filesToRequest SET downloadedChunks = ? WHERE fileID = ?", (json.dumps(list(downloadedChunks)), fileID))
                databaseConn.commit()
            
        except Exception as e:
            self.logger.error(f"Error {e} with fileID {fileID} in RequestFileFromUser" , exc_info=True)

    def FileReturner(self):
        try:
            while not self.shuttingDown:
                time.sleep(self.timeBetweenReturns)
                #Ping each peer 
                self.logger.debug(f"HEARBEATCHECKRUNNING : {self.runningHeartbeatCheck}")
                while(self.runningHeartbeatCheck):
                    self.logger.debug("Waiting for heartbeating to finish")
                    time.sleep(0.1) #Making sure we run AFTER check is done
                
                #Update JSON
                databaseConn = sqlite3.connect("PeersP2PStorage.db")
                cursor = databaseConn.cursor()
                cursor.execute("SELECT * FROM filesToReturn")
                rows = cursor.fetchall()
                UpdateJSON("Files To Return",len(rows),self.serverDataJSONLocation, "ServerData")
                databaseConn.close()
                
                
                self.CheckPeersConnected(source="FILERETURNER")
                for peer in self.peers:   
                    connectionSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    peerIP = self.peers[peer]["ip"]
                    peerPort = self.peers[peer]["port"]
                    userCode = self.peers[peer]["userCode"]
                    
                    #Only send to receiver types
                    self.logger.debug(f"TYPE:  {self.peers[peer]}")
                    if(self.peers[peer]["joinType"] != "receiver"):
                        continue
                    
                    try:
                        self.logger.debug(f"IP {peerIP} PORT {peerPort}")
                        connectionSocket.connect((peerIP,peerPort)) 
                        self.logger.debug("CONNECTION SUCCEEDED")
                        #connectionSocket.setz(10)
                        
                        databaseConn = sqlite3.connect("PeersP2PStorage.db")
                        cursor = databaseConn.cursor()
                        cursor.execute("SELECT * FROM filesToReturn WHERE ownerUserCode = ?", (userCode,))
                        rows = cursor.fetchall()
                        self.logger.debug(f"ROWS IN FILERETURNER : {rows}")
                        for row in rows:
                            self.logger.info(f"RETURNING FILE {row[0]}")
                            self.ReturnFile(row[0], row[1], connectionSocket)
                            cursor.execute("DELETE FROM filesToReturn WHERE ownerUserCode = ?", (userCode,))
                            databaseConn.commit()
                        
                        cursor.execute("SELECT * FROM filesToReturn WHERE ownerUserCode = ?", (userCode,))
                        rows = cursor.fetchall() 
                        self.logger.debug(f"ROWS 123 {rows}")
                            
                        
                    except Exception as e:
                        self.logger.error(f"ERROR : {e} in FileReturner", exc_info=True)

                    finally:
                        connectionSocket.close()
        except Exception as e:
            self.logger.error(f"Error {e} in FileReturner", exc_info=True)

    def ReturnFile(self, fileID, userCode, connectionSocket): 
        try:
            storageFolderPath = self.filesToReturnLocation
            filePath = f"{storageFolderPath}/USERCODE-{userCode}--FILEID-{fileID}.bin"
            with open(filePath, "rb") as fileHandle:
                self.logger.debug(f"Attempting to return {fileID}")
                databaseConn = sqlite3.connect("PeersP2PStorage.db")
                cursor = databaseConn.cursor()
                
                cursor.execute("SELECT * FROM peers WHERE userCode = ?", (userCode,))
                row = cursor.fetchone()
                userIP = row[0]
                userPort = row[1]
                
                self.logger.debug(f"IP {userIP}, PORT : {userPort}")
                requestMessage = {"type" : "fileReturnRequest", "fileID" : fileID}
                
                requestMessage = json.dumps(requestMessage).encode()
                self.logger.debug("SENDING REQUEST IN ReturnFile")
                connectionSocket.send(requestMessage)
                self.logger.debug("SENT REQUEST IN ReturnFile")
                response = connectionSocket.recv(64).decode()
                self.logger.debug(f"RESPONSE {response} in ReturnFile")
                response = json.loads(response)
                if(response) and (response["type"] == "fileReturnRequestAccept"):
                    #Sending data
                    self.logger.debug(f"FILEPATH SIZE IN RF : {math.ceil(os.path.getsize(filePath) / self.chunkSize)}")
                    for i in range(math.ceil(os.path.getsize(filePath) / self.chunkSize)):
                        chunkData = fileHandle.read(self.chunkSize)
                        detailsMessage = json.dumps({"chunkIndex" : i, "chunkLength" : len(chunkData)})
                        self.logger.debug(f"DETAILS MESSAGE IN RF {detailsMessage}")
                        connectionSocket.send(detailsMessage.encode().ljust(64, b"\0"))
                        
                        #Sending chunk
                        connectionSocket.send(chunkData)
                    
            #Clearing the files to return folder of that file
            #os.remove(filePath)   #!TO FIX
                
        except Exception as e:
            self.logger.error(f"Error {e} in ReturnFile", exc_info=True)

    def RequestChunkFromUser(self, targetUserCode, fileID, chunkIndex, ownerUserCode):
        try:
            self.logger.debug(f"REQUESTCHUNKFROMUSER | {targetUserCode} {fileID} {chunkIndex}")

            #Finding IP and port
            databaseConn = sqlite3.connect("PeersP2PStorage.db")
            cursor = databaseConn.cursor()
            
            cursor.execute("SELECT * FROM peers WHERE usercode = ?", (targetUserCode,))
            row = cursor.fetchone()
            self.logger.debug(f"REQUESTCHUNKFROMUSER ROW = {row}")
            targetIPAddress = row[0]
            targetPort = int(row[1])
            
            #Making connection
            connectionSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            connectionSocket.connect((targetIPAddress,targetPort))

            #Sending request
            requestMessage = {"type" : "chunkReceiveRequest"}
            connectionSocket.send(json.dumps(requestMessage).encode())
            
            response = connectionSocket.recv(64).decode()
            self.logger.debug(f"RESPONSE {response} in RequestChunkFromUser")
            
            #Sending details
            
            chunkDetailsMessage = {"chunkIndex" : chunkIndex, "fileID" : fileID, "userCode" : ownerUserCode}
            connectionSocket.send(json.dumps(chunkDetailsMessage).encode())
        
            #Receive chunk data
            chunkData = connectionSocket.recv(self.chunkSize)
            
            self.logger.debug(f"RCFU chunkData len {len(chunkData)}")
            
            databaseConn.close()
            
            return chunkData
            
        except Exception as e:
            self.logger.error(f"Error {e} in RequestChunkFromUser", exc_info=True)        
    
    def AddFileToRequestList(self, fileID): 
        try:
            self.logger.debug("FILE ADDED TO REQUEST LIST")
            conn = sqlite3.connect("PeersP2PStorage.db")  
            cursor = conn.cursor()
            
            #Finding chunk count
            cursor.execute("SELECT * FROM files WHERE fileID = ?",(fileID,))
            row = cursor.fetchone()
            ownerUserCode = row[1]
            chunkCount = row[4]
            
            self.logger.debug(f"{fileID} is of type {type(fileID)}")
            
            
            #Generate file for usage
            folderStoragePath = self.filesToReturnLocation
            fileStorageName = f"{folderStoragePath}/USERCODE-{ownerUserCode}--FILEID-{fileID}.bin"
            with open(fileStorageName, "wb") as fileHandle:
                fileHandle.truncate()
            
            cursor.execute("INSERT INTO filesToRequest (fileID, downloadedChunks, chunkCount, fileStorageName) VALUES (?, ?, ?, ?)", (fileID,json.dumps({}), chunkCount, fileStorageName))
            conn.commit()
            
            self.RequestFileFromUser(fileID)
            
        except sqlite3.IntegrityError:
            self.logger.warning("FileID already in request list")
        except Exception as e:
            self.logger.error(f"Error {e} in AddFileToRequestList", exc_info=True)
        finally:
            conn.close()

    def PeerHeartbeater(self):
        while not self.shuttingDown:
            time.sleep(self.timeBetweenHeartbeats)
            self.logger.info(f"PEERS {self.peers}")
            #Ping each peer 
            
            self.CheckPeersConnected(source="PEERHEARTBEATER")
            
            #Checking timestamp 
            today = date.today()
            currentTimestamp = datetime.now().time()
            currentTimeHours = datetime(today.year,today.month,today.day,currentTimestamp.hour)
            if(self.lastHourReading == None) or ((currentTimeHours - self.lastHourReading) >= (timedelta(hours=1))):
                #Update chart data
                self.logger.debug("UPDATING CHART DATA")
                self.lastHourReading = currentTimeHours
                with self.chartDataLock:
                    with open(self.peerDataCSVLocation, "r") as fileHandle:
                        lines = fileHandle.readlines()
                    while(len(lines) > 719):
                        lines.pop(0)
                    #New Entry
                    lines.append(f"\n{currentTimeHours.hour}--{currentTimeHours.day}-{currentTimeHours.month}-{currentTimeHours.year},{len(self.peers)}")
                    with open(self.peerDataCSVLocation, "w") as fileHandle:
                        fileHandle.writelines(lines)
        
            UpdateJSON("Peers Connected", len(self.peers), self.serverDataJSONLocation, "ServerData")

    def CheckPeersConnected(self, source=None, userCodesToIgnore = []): #Source for debugging purposes
        self.runningHeartbeatCheck = True
        peersToRemove = []
        
        if(source != None):
            print(f"CHECK PEERS CONNECTED SOURCE : {source}")
        
        for peer in self.peers:
            if(self.peers[peer]["userCode"] in userCodesToIgnore):
                continue
        
            connectionSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            peerIP = self.peers[peer]["ip"]
            peerPort = self.peers[peer]["port"]
            
            #Only send to receiver types
            self.logger.debug(f"TYPE:  {self.peers[peer]}")
            if(self.peers[peer]["joinType"] != "receiver"):
                continue
            
            try:
                self.logger.debug(f"IP {peerIP} PORT {peerPort}")
                connectionSocket.connect((peerIP,peerPort)) 
                self.logger.debug(f"CONNECTION SUCCEEDED FOR PEER {peer}, {type(peer)}, {self.peers}, {self.peers[peer]}")
                #connectionSocket.setz(10)
                
                #Sending each peer a ping to see if they are still contactable
                pingMessage = json.dumps({"type": "heartbeatPing"}).encode()
                connectionSocket.send(pingMessage)
                
                #Receiving a response
                response = connectionSocket.recv(1024).decode()
                
                if(response):
                    #Likely peer is still connected
                    self.logger.info(f"{self.peers[peer]['userCode']} is still connected")
                else:
                    #Possible they have disconnected
                    self.logger.info("No response received. Peer may be disconnected.")
                    peersToRemove.append(peer)
            except ConnectionRefusedError as e:
                self.logger.warning("Connection failed. It is likely peer has disconnected")
                peersToRemove.append(peer)
            except Exception as e:
                self.logger.error(f"ERROR : {e} in CheckPeersConnected", exc_info=True)

            finally:
                connectionSocket.close()
            
        for peerToRemove in peersToRemove:
            self.RemoveFromPeers(peerToRemove)

        self.runningHeartbeatCheck = False
    def IncreaseCode(self,code):
        try:
            self.logger.debug(f"INCREASE CODE : {code}")
            code = [*code]
            if(" " in code):
                code.pop(code.index(" "))
            for i in range(len(code)):
                code[i] = ord(code[i])

            code[7] += 1
            for i in range(len(code) - 1, -1, -1):
                if(code[i] > ord("Z")):
                    code[i] = code[i] - 26
                    if(i > 0):
                        code[i-1] += 1
                    else:
                        self.logger.critical("WE ARE OUT OF FILE CODES TO USE")
                        raise IndexError("Ran out of file codes to use")

            code.insert(4, 32)
            codeOutput = ""
            for i in range(len(code)):
                codeOutput += chr(code[i])

            self.logger.debug(f"INCREASE CODE OUTPUT : {code}")
            return codeOutput
        
        except Exception as e:
            self.logger.error(f"Error in FileID increase : {e}", exc_info=True)
            return None

    def start(self):
        self.serverActive = True
        self.serverSocket.bind((self.host, self.port))
        self.serverSocket.listen(5)
        
        with open(preferencesJSONLocation, 'r') as file:
            data = json.load(file)
            self.mainLoggingLevel = loggingLevelDict[data["LogLevel"]]
            server.frontendLogHandler.setLevel(server.mainLoggingLevel)
            self.logger.debug(f"LOGGING LEVEL ON FRONTEND : {self.mainLoggingLevel}")
        
        self.logger.info(f"Signaling server running on {self.host}:{self.port}")
        
        #Setting up SQLite database to store files
        databaseConnection = sqlite3.connect('PeersP2PStorage.db')
        cursor = databaseConnection.cursor()
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS peers (
            ipAddress TEXT NOT NULL,
            port INTEGER NOT NULL,
            userCode TEXT NOT NULL,
            availableSpace INTEGER,
            UNIQUE (userCode)
        )
        ''')

        # Create a table for files
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            fileID TEXT NOT NULL,
            userCode TEXT NOT NULL,
            fileName TEXT NOT NULL,
            fileSize INTEGER NOT NULL,
            chunkCount INTEGER NOT NULL,
            chunkLocations TEXT NOT NULL,
            FOREIGN KEY (userCode) REFERENCES peers (userCode)
        )
        ''')
       
       #Tracker for files to request
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS filesToRequest (
            fileID TEXT NOT NULL UNIQUE,
            downloadedChunks TEXT NOT NULL,
            chunkCount INTEGER NOT NULL,
            fileStorageName TEXT NOT NULL
        )
        ''') 
       
        #Create a tracker to count last used fileID
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS lastUsedFileID (
            lastUsedfileID TEXT NOT NULL
        )
        ''')
        
        #Tracker of files to return 
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS filesToReturn (
            fileID TEXT NOT NULL,
            ownerUserCode TEXT NOT NULL
        )
        ''')
        
        #List of users - used outside the server class
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS userLogins (
            username TEXT NOT NULL UNIQUE,
            password BLOB NOT NULL,
            userCode TEXT NOT NULL UNIQUE
        )
        ''')
        
        
        #Making sure we can properly use lastUsedFileID
        cursor.execute("SELECT * FROM lastUsedFileID")
        
        databaseConnection.close()
        
        #threading.Thread(target=self.Shutdown).start()
        
        #Filling Old Values
        self.FillOldValues()
        
        #Starting File Distributor
        try:
            t = threading.Thread(target= self.FileDistributor, args = (self.filesToSendLocation, ), daemon=True)
            t.start()
            self.threads.append(t)
        except Exception as e:
            self.logger.error(f"Error {e} with file Distribution", exc_info=True)
        
        #Pinging each peer to check theyre connected - heartbeating
        t = threading.Thread(target=self.PeerHeartbeater, args=())
        t.start()
        self.threads.append(t)
        #Starting returner
        t = threading.Thread(target = self.FileReturner, args = ())
        t.start()
        self.threads.append(t)
        t = threading.Thread(target = self.FileDeletor, args = ())
        t.start()
        self.threads.append(t)
        try:
            while not self.shuttingDown:
                self.logger.info("Waiting for peer connections...")
                if not self.shuttingDown:
                    peer_socket, addr = self.serverSocket.accept()
                    self.logger.info(f"Message on {addr}")
                    if(not addr in self.connectedAddrs):
                        self.logger.info(f"New connection from {addr}")
                        self.connectedAddrs.append(addr)

                        # Handle each peer in a separate thread
                        t = threading.Thread(target=self.handle_peer, args=(peer_socket,), daemon=True)
                        t.start()
                        self.threads.append(t)
                        self.logger.warning("NEW THREAD CREATED")
        except Exception as e:
            if(not isinstance(e, OSError) and getattr(e, "winerror", None) == 10038):
                self.logger.error(f"Error {e} in start")
                        

    def SendChunkToPeer(self, userCode, chunk,chunkIndex, chunkSize, fileID):
        #Choosing who to send to
        self.logger.debug("TESTING 1")
        connection = sqlite3.connect('PeersP2PStorage.db')
        cursor = connection.cursor()

        cursor.execute('SELECT * FROM peers')
    
        # Fetch all rows
        rows = cursor.fetchall()
        self.logger.debug(f"ROWS {rows}")
        
        targetUsers = []
        
        #Make sure we dont attempt to send to someone whos not on
        self.CheckPeersConnected(source="SENDCHUNKTOPEER", userCodesToIgnore=[userCode])
        
        for i in range(1 + self.redundancyValue):
            self.logger.debug("TESTING 2")
            # Iterate through the rows to find a match
            chosenPeer = None
            lowestConsumedSpace = self.spacePerPeerMB*1024*1024 + 1 #Everybody should be lower than this
            for row in rows:
                row = list(row)
                row[3] = float(row[3])
                self.logger.debug(f"ROW {row} SIZE {chunkSize} {lowestConsumedSpace}")
                #Dont send to the same guy twice | Don't send to owner of chunk
                if(row in targetUsers) or (row[2] == userCode):
                    continue
                
                # Check if any column in the row matches your search value
                if (row[3] < lowestConsumedSpace) and (row[3] >= chunkSize):  #If it is less full than the currently least full AND it has space for the file
                    lowestConsumedSpace = row[3]
                    chosenPeer = row
                    if(chosenPeer[3] == 0): #Person is completely empty - we will not find someone emptier
                        break
            
            if chosenPeer != None:
                targetUsers.append(chosenPeer)   
                #Decreasing target user's storage space
                cursor.execute("UPDATE peers SET availableSpace = ? WHERE userCode = ?", (chosenPeer[3] - chunkSize, chosenPeer[2]))    
                connection.commit()
            else:
                self.logger.debug("No space")

        self.logger.info(f"FOUND USERS {targetUsers}") 
        #Sending file to peers
        for targetUser in targetUsers:
            #Sending request
            self.logger.debug(f"SENDING REQUEST TO {targetUser}")
            peerSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            
            peerSocket.connect((targetUser[0],targetUser[1]))
            self.logger.debug(f"Server is sending data to {peerSocket.getsockname()}")
            self.logger.debug("TEST 1")
            chunkSendMessage = {"type" : "chunkStoreRequest"}
            peerSocket.send(json.dumps(chunkSendMessage).encode())
            self.logger.debug("SEND REQUEST SUCCEEDED")
            peerSocketReception = peerSocket.recv(64)
            peerSocketReception = json.loads(peerSocketReception.decode())
            if(peerSocketReception["type"] == "chunkStoreResponseAccept"):
                self.logger.debug(f"WE CAN SEND TO {targetUser}")

                #Send Chunk Data
                chunkData = {"userCode" : userCode, "chunkIndex" : chunkIndex, "fileID" : fileID}
                chunkData = json.dumps(chunkData).encode()
                chunkData = chunkData.ljust(128, b' ') #Padding to 128 bytes
                peerSocket.send(chunkData) 
                #Send actual chunk
                peerSocket.send(chunk) #Up to 1024 bytes
                
        # Close the connection
        connection.close()
        
        #Returning information back
        return {"chunkIndex" : chunkIndex, "userCodes" : targetUsers}
    
    def FileDistributor(self, folderFilePath):
        try:
            while not self.shuttingDown: 
                
                with self.fileDeletionLock:
                    #Loop through all files
                    self.logger.debug("LOOPING THROUGH FILES TO DISTRIBUTE")
                    counter = 0
                    filesList = os.listdir(folderFilePath)
                    while(counter < len(filesList)):
                        fileTarget = filesList[counter].split("--")
                        self.logger.debug(f"FILE ID = {fileTarget[2].strip('fileID')} | {self.completedFileIDs}")
                        
                        fileTarget[2] = fileTarget[2].strip("fileID").strip(".bin")
                        if(fileTarget[2] in self.completedFileIDs):
                            self.logger.debug(f"NOW ATTEMPTING TO DISTRIBUTE {fileTarget} | {fileTarget[2]}")
                            
                            if(self.DistributeFileToPeers(filesList[counter], (folderFilePath + "\\" + filesList[counter]))):
                                os.remove(folderFilePath + "\\" + filesList[counter])
                                self.completedFileIDs.remove(fileTarget[2])
                            else:
                                counter += 1
                                self.logger.warning(f"ISSUE DISTRIBUTING {filesList}")
                        else:
                            counter += 1
                            self.logger.warning(f"CANNOT DISTRIBUTE {filesList} - NOT READY")
                    
                    UpdateJSON("Files In Storage", len(os.listdir(folderFilePath)), self.serverDataJSONLocation, "ServerData")
                
                #Waiting for a bit to avoid spam 
                time.sleep(10)
        
        except Exception as e:
            self.logger.error(f"Error {e} in FileDistributor", exc_info=True)
    
    def DistributeFileToPeers(self, fileName, filePath):
        try:
            fileNameCopy = fileName.split("--")
            self.logger.debug(f"FILENAMECOPY {fileNameCopy}")
            userCode = (fileNameCopy[0].strip("userCode"))
            
            totalChunkCount = math.ceil(os.path.getsize(filePath) / self.chunkSize)
            
            self.logger.debug("TEST 1")
            
            #Finding code to use
            conn = sqlite3.connect("PeersP2PStorage.db")
            cursor = conn.cursor()
            # cursor.execute("SELECT * FROM lastUsedFileID")
            
            # self.logger.debug(f"TEST 1.1   |{self.lastUsedFileID}")

            # if(self.lastUsedFileID == None):
            #     self.lastUsedFileID ="AAAA AAAA"
            
            # fileID = (self.lastUsedFileID)
            
            fileID = (fileNameCopy[2]).lstrip("fileID").rstrip(".bin")
            
            self.logger.debug(f"FILEID : {fileID}")
            self.logger.debug("TEST 2")
            
            #Updating FileID database
            cursor.execute("UPDATE lastUsedFileID SET lastUsedFileID = ?;", (fileID,)) 
            conn.commit()
            
            self.logger.debug("TEST 3")
            
            chunksDetails = []
            chunksSent = True
            
            with open(filePath, "rb") as fileHandle:
                for chunkCount in range(totalChunkCount):
                    chunk = fileHandle.read(self.chunkSize) 
                    
                    chunkDetails = self.SendChunkToPeer(userCode,chunk,chunkCount,len(chunk),fileID)
                    self.logger.debug(f"CHUNK DETAILS : {chunkDetails}")
                    chunksDetails.append(chunkDetails)
                    
                if(chunkDetails["userCodes"] == []):
                    chunksSent = False
                
                else:
                    #Updating file SQL
                    try:
                        self.logger.debug(f"JSON DUMPS : {json.dumps(chunksDetails)} {type(json.dumps(chunksDetails))}")
                        self.logger.debug(f"TYPES : {type(fileID)} | {type(userCode)} | {type(fileName)} | {type(os.path.getsize(filePath))} | {type(json.dumps(chunksDetails))}")
                        self.logger.debug(f"FILE NAME {fileName}")
                        cursor.execute('''
                            INSERT INTO files (fileID, userCode, fileName, fileSize, chunkCount, chunkLocations)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ''', (fileID, userCode, fileName, os.path.getsize(filePath), totalChunkCount, json.dumps(chunksDetails))
                            )
                        conn.commit()
                
                        self.logger.debug("TEST 4")
                        
                    except Exception as e:
                        self.logger.error(f"ERROR {e} UPDATING files in DistributeFileToPeers", exc_info=True)

                self.logger.debug(f"CHUNKS SENT CHECK: {chunksSent}")
        except Exception as e:
            self.logger.error(f"Error {e} in DistributeFileToPeers", exc_info=True)
        finally:
            conn.close()
            return chunksSent
        
    def AcceptFileFromPeer(self, userCode, pConnection):
        try:
            self.logger.info("ACCEPT FROM PEER BEGAN")
            pConnection.send(json.dumps({"type" : "uploadPong", "status" : "accept"}).encode())
            totalChunkCount = int(pConnection.recv(8).decode())
            receivedChunks = []
            normalChunkIndexes = []
            brokenChunkIndexes = []
            missingChunkIndexes = []
            for i in range(totalChunkCount):
                self.logger.info(f"TOTAL CHUNK COUNT {totalChunkCount}")
                chunkIndex = int(pConnection.recv(8).decode())
                chunk = pConnection.recv(self.chunkSize)
                if(len(chunk) == self.chunkSize):
                    #Everything has gone well
                    self.logger.debug(f"LEN {len(chunk)}") 
                    #Unpadding
                    if chunkIndex == totalChunkCount - 1:
                        unpadder = padding.PKCS7(128).unpadder()
                        try:
                            chunk = unpadder.update(chunk.rstrip(b"\0")) + unpadder.finalize()
                            self.logger.debug("UNPADDED")
                        except ValueError as e:
                            self.logger.error(f"Unpadding error: {e}", exc_info=True)
                    
                    self.logger.debug(f"FINAL")
                    normalChunkIndexes.append(chunkIndex)
                    receivedChunks.append(chunk)
                else:
                    #Something has gone wrong
                    brokenChunkIndexes.append(i)
                    

            #Checking for missing chunks
            for i in range(totalChunkCount):
                if(i in normalChunkIndexes):
                    continue
                missingChunkIndexes.append(i)
            
            self.logger.info(f"MISSING {missingChunkIndexes}")
            self.logger.info(f"NORMAL {normalChunkIndexes}")
            self.logger.info(f"BROKEN {brokenChunkIndexes}")
            
            #Finding file code
            self.logger.debug(f"TEST 1.2   |{self.lastUsedFileID}")
            
            with self.fileIDLock:
                databaseConn = sqlite3.connect("PeersP2PStorage.db")
                cursor = databaseConn.cursor()
                
                cursor.execute("SELECT * FROM lastUsedFileID")
                row = cursor.fetchone()
                if(row == None):
                    self.lastUsedFileID = "AAAA AAAA"
                else:
                    self.lastUsedFileID = row[0]
                
                self.logger.debug(f"TEST 1.3   |{self.lastUsedFileID}")
                
                fileID = self.IncreaseCode(self.lastUsedFileID)
                self.logger.debug(f"TEST 1.4 : {fileID}")
                fileName = f"userCode{userCode}--{datetime.now().strftime('%d_%m_%Y-%H_%M_%S')}--fileID{fileID}.bin"
                if(row == None):
                    cursor.execute("INSERT INTO lastUsedFileID (lastUsedfileID) VALUES (?);", (fileID,))
                else:
                    cursor.execute("UPDATE lastUsedFileID SET lastUsedFileID = ?;", (fileID,))
                databaseConn.commit()
                databaseConn.close()
            
            with open(rf"Files To Send\{fileName}", "wb") as fileHandle:
                for chunk in receivedChunks:
                    fileHandle.write(chunk)
            self.completedFileIDs.append(fileID)
        
            #Sending fileIDMessage    
            fileIDMessage = json.dumps({"type" : "fileIDSend", "fileID" : fileID})
            pConnection.send(fileIDMessage.encode())
        
        except Exception as e:
            self.logger.error(f"Error {e} in AcceptFileFromPeer", exc_info=True)

#*Flask shenanigans
app = Flask(__name__)
CORS(app)  # Allows cross-origin requests
preferencesJSONLock = threading.Lock()
serverDataJSONLock = threading.Lock()
accountCreationLock = threading.Lock()

#.env data
frontendLogLocation = os.getenv("FRONTEND_LOG_LOCATION")
peerDataCSVLocation = os.getenv("PEER_DATA_CSV_LOCATION")
serverDataJSONLocation = os.getenv("SERVER_DATA_JSON_LOCATION")
themesJSONLocation = os.getenv("THEMES_JSON_LOCATION")
preferencesJSONLocation = os.getenv("PREFERENCES_JSON_LOCATION")

@app.route('/api/Themes', methods=['GET'])
def ReturnThemeJSON():
    try:
        with open(themesJSONLocation, 'r') as file:
            data = json.load(file)
        return jsonify(data) 
    
    except FileNotFoundError:
        return jsonify({"error": "Themes.json not found"}), 404
    
    except json.JSONDecodeError:
        return jsonify({"error": "Themes.json is not valid JSON"}), 500
    
@app.route('/api/Log', methods=['GET'])
def ReturnLog():
    try:
        with open(frontendLogLocation, 'r') as file:
            data = file.read()  # Read the content of the log file as text
        return Response(data, mimetype='text/plain')  # Return plain text response
    
    except FileNotFoundError:
        return jsonify({"error": "Test.log not found"}), 404
    
    except Exception as e:
        server.logger.error(f"Error {e} in ReturnLog", exc_info=True)
        return jsonify({"error": f"An unexpected error occurred - check log"}), 500

@app.route('/api/Preferences', methods=['GET'])
def ReturnPreferences():
    try:
        with open(preferencesJSONLocation, 'r') as file:
            data = json.load(file)
        return jsonify(data) 
    
    except FileNotFoundError:
        return jsonify({"error": "Preferences.json not found"}), 404
    
    except json.JSONDecodeError:
        return jsonify({"error": "Preferences.json is not valid JSON"}), 500

@app.route('/api/ServerData', methods=['GET'])
def ReturnServerData():
    try:
        with open(serverDataJSONLocation, 'r') as file:
            data = json.load(file)
        return jsonify(data) 
    
    except FileNotFoundError:
        return jsonify({"error": "ServerData.json not found"}), 404
    
    except json.JSONDecodeError:
        return jsonify({"error": "ServerData.json is not valid JSON"}), 500

@app.route('/api/ServerCSV', methods=['GET'])
def ReturnServerCSV():
    try:
        with open(peerDataCSVLocation, 'r') as file:
            csv_reader = csv.reader(file)
            data = []
            for row in csv_reader:
                timestamp = row[0]
                date = (timestamp.split("--")[1]).split("-")
                hour = timestamp.split("--")[0]
                datetimeObject = datetime(int(date[2]), int(date[1]), int(date[0]), int(hour))
                dayLabel = datetimeObject.strftime("%A")[0:3]
                dateLabel = f'{dayLabel} {datetimeObject.strftime("%H:00 %d-%m-%Y")}'
                data.append([dateLabel, row[1]])       
        
        return jsonify(data) 
    
    except FileNotFoundError:
        return jsonify({"error": "PeerData.csv not found"}), 404
    
    except json.JSONDecodeError:
        return jsonify({"error": "PeerData.csv   is not valid JSON"}), 500

def UpdateJSON(key, value, path, lockType):
    lockTypeDict = {
        "Preference" : preferencesJSONLock,
        "ServerData" : serverDataJSONLock,
    }
    lockType = lockTypeDict[lockType]
    with lockType:
        with open(path, "r") as fileHandle:
            data = json.load(fileHandle)
            data[key] = value
        with open(path, "w") as fileHandle:
            json.dump(data, fileHandle, indent=4)

@app.route('/api/Post/LogLevel', methods=['POST'])
def UpdateLogLevel():
    content = request.json  # Get JSON from the request body
    print("Received:", content)
    #update logging software
    newLogLevel = content["logLevel"]
    
    server.mainLoggingLevel = loggingLevelDict[newLogLevel]
    server.frontendLogHandler.setLevel(server.mainLoggingLevel)
    
    #Updating jsons
    UpdateJSON("LogLevel", newLogLevel, preferencesJSONLocation, "Preference")
    return jsonify({"message": "Data received!", "received": content})

@app.route('/api/Post/ChangeThemePreference', methods=['POST'])
def ChangeThemePreferences():
    content = request.json  # Get JSON from the request body
    print("Received:", content)
    #update logging software
    newColour = content["colour"]
    
    #Updating jsons
    UpdateJSON("Theme", newColour, preferencesJSONLocation, "Preference")
    return jsonify({"message": "Data received!", "received": content})

@app.route('/api/Post/UpdateChartType', methods=['POST'])
def UpdateChartType():
    content = request.json  # Get JSON from the request body
    print("Received:", content)
    #update logging software
    newChartType = content["ChartType"]
    
    #Updating jsons
    UpdateJSON("ChartType", newChartType, preferencesJSONLocation, "Preference")
    return jsonify({"message": "Data received!", "received": content})
    
@app.route('/api/Post/ShutdownServer', methods=['POST'])
def ShutdownServer():
    content = request.json  # Get JSON from the request body
    threading.Thread(target=server.Shutdown).start()
    return jsonify({"message": "Data received!", "received": content})

@app.route('/api/ServerStatus', methods=['GET'])
def ReturnServerStatus():
    try:
        return jsonify({"serverStatus" : server.serverActive}) 
    
    except:
        return jsonify({"serverStatus" : None})
    
@app.route('/api/Post/ClearLog', methods=['POST'])
def ClearLog():
    with serverDataJSONLock:
        content = request.json  # Get JSON from the request body
        with open(frontendLogLocation, "w") as fileHandle:
            pass #For some reason this clears the file
        return jsonify({"message": "Data received!", "received": content})
    
@app.route('/api/Post/StartServer', methods=['POST'])
def StartServer():
    content = request.json  # Get JSON from the request body
    if not(server.serverActive):
        server.start()
    return jsonify({"message": "Data received!", "received": content})

@app.route("/LoginRequest", methods=["POST"])
def LoginRequest():
    data = request.json
    
    username = data["username"]
    password = data["password"]
    passwordBytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    
    databaseConn = sqlite3.connect("PeersP2PStorage.db")
    cursor = databaseConn.cursor()
    cursor.execute("SELECT * FROM userLogins WHERE username = ?", (username,))
    row = cursor.fetchone()
    userCode = ""
    if(row != None):
        databasePassword = row[1] 
        status = bcrypt.checkpw(passwordBytes, databasePassword)
        server.logger.debug(f"BCRPYT STATUS : {bcrypt.checkpw(passwordBytes, databasePassword)}, {passwordBytes}, {databasePassword}")
        userCode = row[2]
    else:
        #Not in database
        status = False
    server.logger.info(f"LOGIN STATUS {status}")
    return jsonify({"status" : str(status), "userCode" : userCode}), 200

def IncrementString(s):
    number = int(s.replace(" ", ""))
    incremented = number + 1
    formatted = f"{incremented:016d}"
    return ' '.join(formatted[i:i+4] for i in range(0, 16, 4))

@app.route("/AccountCreationRequest", methods=["POST"])
def AccountCreationRequest():
    with accountCreationLock:
        data = request.json
        
        username = data["username"]
        password = data["password"]
        passwordBytes = password.encode("utf-8")
        salt = bcrypt.gensalt()
        passwordHashed = bcrypt.hashpw(passwordBytes, salt)
        
        databaseConn = sqlite3.connect("PeersP2PStorage.db")
        cursor = databaseConn.cursor()
        cursor.execute("SELECT * FROM userLogins WHERE username = ?", (username,))
        row = cursor.fetchall()
        
        failureCondition = ""
        newUserCode = ""
        if(row != []):
            #Username already in database
            status = False
            failureCondition = "Username already in use"
        else:
            #Finding the next ID to use
            cursor.execute("SELECT * FROM userLogins ORDER BY userCode DESC LIMIT 1")
            row = cursor.fetchone()
            if(row == None):
                #Nothing in SQL
                newUserCode = "0000 0000 0000 0001"
            else:
                newUserCode = IncrementString(row[2])
            
            #Adding the user to the SQL
            cursor.execute("INSERT INTO userLogins (username, password, userCode) VALUES (?, ?, ?)", (username, passwordHashed, newUserCode))
            databaseConn.commit()
            status = True
        
        databaseConn.close()
            
        server.logger.info(f"LOGIN STATUS {status}")
        return jsonify({"status" : str(status), "failureCondition" : failureCondition, "userCode" : newUserCode}), 200

if __name__ == '__main__':
    server = SignalingServer()
    #Starting up server
    threading.Thread(target=server.start).start()
    
    #Starting website
    #print(sslCertificateLocation + "/cert.pem")
    app.run(port=5000, debug=False, ssl_context=(sslCertificateLocation +'/cert.pem', sslCertificateLocation + '/key.pem'))