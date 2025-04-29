import socket
import json
import threading
import time
import sqlite3
from datetime import datetime
from cryptography.hazmat.primitives import padding
import os
import math
import logging
import colorlog
from Debug import ResetSystem

#!TEMP
if(input("SHOULD RESET FOLDERS (Y/N): ").strip().upper() == "Y"):
    ResetSystem.ClearFolders([r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Files To Send",r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Received Files", r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Files To Return"])

#!TEMP
if(os.path.exists(f"ServerGeneral.log")):
    os.remove("PeersP2PStorage.db")
    os.remove(f"ServerGeneral.log")
    os.remove(f"ServerErrors.log")
    
# Signaling server class
class SignalingServer:
    def __init__(self, host='0.0.0.0', port=12345):
        self.host = host
        self.port = port
        self.peers = {}
        self.lock = threading.Lock()  # Lock to ensure thread safety for shared data
        self.timeBetweenHeartbeats = 10
        self.spacePerPeerMB = 1024
        self.redundancyValue = 0 #1 Redundancy Peer
        self.connectedAddrs = []
        self.completedFileIDs = []
        self.storedRequestedFilesData = []
        self.timeBetweenReturns = 10
        self.runningHeartbeatCheck = False
        
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

        # Create a file handler for "app.log"
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
            
            threading.Thread(threading.Thread(target= self.RequestFilesFromUser, args = (), daemon=True).start())
            
            
            if("type" in peer_info):
                if(peer_info["type"] == "uploadPing"):
                    self.logger.info("ACCEPTING FILE")
                    self.AcceptFileFromPeer(peer_info["userCode"], peer_socket)
                elif(peer_info["type"] == "requestPing"):
                    self.logger.debug(f"FILE REQUEST FOR FILE {peer_info['fileID']}")
                    
                    #Add file to request list   
                    self.AddFileToRequestList(peer_info['fileID'])
            else:
                peer_ip = peer_info['ip']
                peer_port = peer_info['port']
                peerUserCode = peer_info['userCode']
                self.logger.info(f"New peer connected: {peer_ip}:{peer_port}")

                # Store peer info in a thread-safe manner
                with self.lock:
                    self.peers[f"{peer_ip}:{peer_port}"] = peer_info

                # Send the updated peers list to the connecting peer
                with self.lock:
                    peer_socket.send(json.dumps(self.peers).encode())

                self.logger.info(f"Current peers list: {self.peers}")  # Debug message
                
                #Try adding to the database
                try:
                    cursor.execute('''
                    INSERT INTO peers (ipAddress, port, userCode, availableSpace)
                    VALUES (?, ?, ?, ?)
                    ''', (peer_ip, peer_port, peerUserCode, self.spacePerPeerMB * 1024 * 1024))  #Converting into B from MB
                    databaseConnection.commit()
                    self.logger.info("User commited to database")
                except sqlite3.IntegrityError as e:  # Catch IntegrityError specifically
                    self.logger.warning(f"Database Error: {e}")
                    self.logger.warning("User already in database")
                except Exception as e:  # Catch any other exceptions
                    self.logger.error(f"Unexpected Error: {e}")
                finally:
                    databaseConnection.close()
        except Exception as e:
            self.logger.error(f"Error handling peer: {e}")
        finally:
            peer_socket.close()

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
            self.logger.error(f"Error {e} in RequestFilesFromUser")

    def RemoveFromPeers(self, ipPortCode):
        try:
            for peer in self.peers:
                if(peer == ipPortCode):
                    del self.peers[ipPortCode]
                    break
        except Exception as e:
            self.logger.error(f"Error {e} in RemoveFromPeers")

    def AddChunkToFile(self, fileName, chunkIndex, chunkData):
        try:
            with open(fileName, "r+b") as fileHandle:
                offset = chunkIndex * 1024
                fileHandle.seek(offset)
                fileHandle.write(chunkData)
        except Exception as e:
            self.logger.error(f"Error {e} in AddChunkToFile")

    def RequestFileFromUser(self, fileID):
        try:
            
            databaseConn = sqlite3.connect("PeersP2PStorage.db")
            self.logger.debug(f"REQUESTING FILE {fileID}")
            cursor = databaseConn.cursor()
            cursor.execute("SELECT * FROM files WHERE fileID = ?", (fileID,))
            row = cursor.fetchone()
            
            ownerUserCode = row[1]
            chunkLocations = json.loads(row[5])
            
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
                    
                    #!TEMP
                    self.logger.debug(f"OUTPUT OF RequestFileFromUser : {chunkData.decode()}")    
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
            self.logger.error(f"Error {e} with fileID {fileID} in RequestFileFromUser")

    def FileReturner(self):
        try:
            while True:
                time.sleep(self.timeBetweenReturns)
                #Ping each peer 
                self.logger.debug(f"HEARBEATCHECKRUNNING : {self.runningHeartbeatCheck}")
                while(self.runningHeartbeatCheck):
                    self.logger.debug("Waiting for heartbeating to finish")
                    time.sleep(0.1) #Making sure we run AFTER check is done
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
                            self.ReturnFile(row[0], row[1])
                            cursor.execute("DELETE FROM filesToReturn WHERE ownerUserCode = ?", (userCode,))
                            databaseConn.commit()
                            
                            
                        
                    except Exception as e:
                        self.logger.error(f"ERROR : {e} in FileReturner")

                    finally:
                        connectionSocket.close()
        except Exception as e:
            self.logger.error(f"Error {e} in FileReturner")

    def ReturnFile(self, fileID, userCode):
        try:
            storageFolderPath = r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Files To Return"
            filePath = f"{storageFolderPath}/USERCODE-{userCode}--FILEID-{fileID}.bin"
            with open(filePath, "rb") as fileHandle:
                self.logger.debug(f"Attempting to return {fileID}")
                databaseConn = sqlite3.connect("PeersP2PStorage.db")
                cursor = databaseConn.cursor()
                
                cursor.execute("SELECT * FROM peers WHERE userCode = ?", (userCode,))
                row = cursor.fetchone()
                userIP = row[0]
                userPort = row[1]
                
                connectionSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                connectionSocket.connect((userIP,userPort))
                
                self.logger.debug(f"IP {userIP}, PORT : {userPort}")
                requestMessage = {"type" : "fileReturnRequest"}
                requestMessage = json.dumps(requestMessage).encode()
                self.logger.debug("SENDING REQUEST IN ReturnFile")
                connectionSocket.send(requestMessage.ljust(64, b" "))
                self.logger.debug("SENT REQUEST IN ReturnFile")
                response = connectionSocket.recv(64).decode()
                self.logger.debug(f"RESPONSE {response} in ReturnFile")
                response = json.loads(response)
                if(response) and (response["type"] == "fileReturnRequestAccept"):
                    #Sending data
                    for i in range(math.ceil(os.path.getsize(filePath) / 1024)):
                        chunkData = fileHandle.read(1024)
                        detailsMessage = json.dumps({"chunkIndex" : i, "chunkLength" : len(chunkData)}).ljust(64)
                        connectionSocket.send(detailsMessage.encode())
                        
                        #Sending chunk
                        connectionSocket.send(chunkData)
                        
                
        except Exception as e:
            self.logger.error(f"Error {e} in ReturnFile")

    def RequestChunkFromUser(self, targetUserCode, fileID, chunkIndex, ownerUserCode): #TODO
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
            #!LABEL
            chunkDetailsMessage = {"chunkIndex" : chunkIndex, "fileID" : fileID, "userCode" : ownerUserCode}
            connectionSocket.send(json.dumps(chunkDetailsMessage).encode())
        
            #Receive chunk data
            chunkData = connectionSocket.recv(1024)
            
            databaseConn.close()
            
            return chunkData
            
        except Exception as e:
            self.logger.error(f"Error {e} in RequestChunkFromUser")        
    
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
            folderStoragePath = r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Files To Return"
            fileStorageName = f"{folderStoragePath}/USERCODE-{ownerUserCode}--FILEID-{fileID}.bin"
            with open(fileStorageName, "wb") as fileHandle:
                fileHandle.truncate()
            
            cursor.execute("INSERT INTO filesToRequest (fileID, downloadedChunks, chunkCount, fileStorageName) VALUES (?, ?, ?, ?)", (fileID,json.dumps({}), chunkCount, fileStorageName))
            conn.commit()
            
            #!TEMP
            self.RequestFileFromUser(fileID)
            
        except sqlite3.IntegrityError:
            self.logger.warning("FileID already in request list")
        except Exception as e:
            self.logger.error(f"Error {e} in AddFileToRequestList")
        finally:
            conn.close()

    def PeerHeartbeater(self):
        while True:
            time.sleep(self.timeBetweenHeartbeats)
            self.logger.info(f"PEERS {self.peers}")
            #Ping each peer 
            
            self.CheckPeersConnected()

    def CheckPeersConnected(self):
        self.runningHeartbeatCheck = True
        peersToRemove = []
        for peer in self.peers:
            
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
                self.logger.debug("CONNECTION SUCCEEDED")
                #connectionSocket.setz(10)
                
                #Sending each peer a ping to see if they are still contactable
                pingMessage = json.dumps({"type": "heartbeatPing", "message": "Are you still there?"}).encode()
                connectionSocket.send(pingMessage)
                
                #Receiving a response
                response = connectionSocket.recv(1024).decode()
                
                if(response):
                    #Likely peer is still connected
                    self.logger.info(f"{self.peers[peer]['name']} is still connected")
                else:
                    #Possible they have disconnected
                    self.logger.info("No response received. Peer may be disconnected.")
                    peersToRemove.append(peer)
            except ConnectionRefusedError as e:
                self.logger.warning("Connection failed. It is likely peer has disconnected")
                peersToRemove.append(peer)
            except Exception as e:
                self.logger.error(f"ERROR : {e} in CheckPeersConnected")

            finally:
                connectionSocket.close()
            
        for peerToRemove in peersToRemove:
            self.RemoveFromPeers(peerToRemove)

        self.runningHeartbeatCheck = False
    def IncreaseCode(self,code):
        try:
            code = [*code]
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


            codeOutput = ""
            for i in range(len(code)):
                codeOutput += chr(code[i])

            return codeOutput
        except Exception as e:
            self.logger.error(f"Error in FileID increase : {e}")
            return None

    def start(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.bind((self.host, self.port))
        server_socket.listen(5)
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
        
        #Making sure we can properly use lastUsedFileID
        cursor.execute("SELECT * FROM lastUsedFileID")
        
        databaseConnection.close()
        
        #Starting File Distributor
        try:
            threading.Thread(target= self.FileDistributor, args = (r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Files To Send", ), daemon=True).start()
        except Exception as e:
            self.logger.error(f"Error {e} with file Distribution")
        
        #Pinging each peer to check theyre connected - heartbeating
        threading.Thread(target=self.PeerHeartbeater, args=()).start()
        
        #Starting returner
        threading.Thread(target = self.FileReturner, args = ()).start()
        
        while True:
            self.logger.info("Waiting for peer connections...")
            peer_socket, addr = server_socket.accept()
            self.logger.info(f"Message on {addr}")
            if(not addr in self.connectedAddrs):
                self.logger.info(f"New connection from {addr}")
                self.connectedAddrs.append(addr)

                # Handle each peer in a separate thread
                threading.Thread(target=self.handle_peer, args=(peer_socket,), daemon=True).start()
                self.logger.warning("NEW THREAD CREATED")
                #self.handle_peer(peer_socket)

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
                chunkData = chunkData.ljust(128, b'\0') #Padding to 128 bytes
                peerSocket.send(chunkData) 
                #Send actual chunk
                peerSocket.send(chunk) #Up to 1024 bytes
                
        # Close the connection
        connection.close()
        
        #Returning information back
        return {"chunkIndex" : chunkIndex, "userCodes" : targetUsers}
    
    def FileDistributor(self, folderFilePath):
        try:
            while True:
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
                
                #Waiting for a bit to avoid spam 
                time.sleep(10)
        
        except Exception as e:
            self.logger.error(f"Error {e} in FileDistributor")
    
    def DistributeFileToPeers(self, fileName, filePath):
        try:
            fileNameCopy = fileName.split("--")
            userCode = (fileNameCopy[0].strip("userCode"))
            
            totalChunkCount = math.ceil(os.path.getsize(filePath) / 1024)
            
            self.logger.debug("TEST 1")
            
            #Finding code to use
            conn = sqlite3.connect("PeersP2PStorage.db")
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM lastUsedFileID")
            lastUsedID = cursor.fetchall()
            
            self.logger.debug(f"TEST 1.1   |{lastUsedID}")
            
            if(lastUsedID != None) and (lastUsedID != []):
                lastUsedID = lastUsedID[0][0]
                fileID = self.IncreaseCode(lastUsedID)
            else:
                fileID = "AAAA AAAA"
            
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
                    chunk = fileHandle.read(1024)
                    
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
                        self.logger.error(f"ERROR {e} UPDATING files in DistributeFileToPeers")

                self.logger.debug(f"CHUNKS SENT CHECK: {chunksSent}")
        except Exception as e:
            self.logger.error(f"Error {e} in DistributeFileToPeers")
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
                chunk = pConnection.recv(1024)
                if(len(chunk) == 1024):
                    #Everything has gone well
                    self.logger.debug(f"LEN {len(chunk)}") 
                    #Unpadding
                    if chunkIndex == totalChunkCount - 1:
                        unpadder = padding.PKCS7(128).unpadder()
                        try:
                            chunk = unpadder.update(chunk.rstrip(b"\0")) + unpadder.finalize()
                            self.logger.debug("UNPADDED")
                        except ValueError as e:
                            self.logger.error(f"Unpadding error: {e}")
                    
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
            conn = sqlite3.connect("PeersP2PStorage.db")
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM lastUsedFileID")
            lastUsedID = cursor.fetchall()
            
            self.logger.debug(f"TEST 1.1   |{lastUsedID}")
            
            if(lastUsedID != None) and (lastUsedID != []):
                lastUsedID = lastUsedID[0][0]
                fileID = self.IncreaseCode(lastUsedID)
            else:
                fileID = "AAAA AAAA"
            
            conn.close()
            
            fileName = f"userCode{userCode}--{datetime.now().strftime('%d_%m_%Y-%H_%M_%S')}--fileID{fileID}.bin"
            
            
            with open(rf"Files To Send\{fileName}", "wb") as fileHandle:
                for chunk in receivedChunks:
                    fileHandle.write(chunk)
            self.completedFileIDs.append(fileID)
        
            #Sending fileIDMessage    
            fileIDMessage = json.dumps({"type" : "fileIDSend", "fileID" : fileID}).ljust(64,"\0")
            pConnection.send(fileIDMessage.encode())
        
        except Exception as e:
            self.logger.error(f"Error {e} in AcceptFileFromPeer")
    
    
if __name__ == '__main__':
    server = SignalingServer()
    server.start()