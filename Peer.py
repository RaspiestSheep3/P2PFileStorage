import socket
import json
import threading
from datetime import datetime
import os
from cryptography.hazmat.primitives import padding
import logging
import colorlog
import sqlite3
import math

waitingForFiles = True
deviceName = datetime.now().strftime("%H:%M:%S")
userCode = input("USER CODE : ") #!TEMP
testPort = int(input("TARGET PORT : ")) #!TEMP

#!TEMP
if(input("SHOULD DELETE FILES? : ").strip().upper() == "Y"):
    if(os.path.exists(f"Peer{userCode}General.log")):
        os.remove(f"Peer{userCode}General.log")
    if(os.path.exists(f"Peer{userCode}Errors.log")):
        os.remove(f"Peer{userCode}Errors.log")
    if(os.path.exists(f"Peer{userCode}FileDatabse.db")):
        os.remove(f"Peer{userCode}FileDatabse.db")

class Peer:
    def __init__(self, signalingServerHost='127.0.0.1', signalingServerPort=12345, name=""):
        self.signalingServerHost = signalingServerHost
        self.signalingServerPort = signalingServerPort
        self.name = name
        self.peerSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

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
        self.generalLogHandler = logging.FileHandler(f"Peer{userCode}General.log")
        self.generalLogHandler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        self.generalLogHandler.setLevel(logging.DEBUG)  

        # Create a file handler for "shared.log"
        self.errorLogHandler = logging.FileHandler(f"Peer{userCode}Errors.log")
        self.errorLogHandler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        self.errorLogHandler.setLevel(logging.ERROR)  

        # Create a logger
        self.logger = logging.getLogger("colorLogger")
        self.logger.setLevel(logging.DEBUG)

        # Add handlers to the logger
        self.logger.addHandler(self.consoleLogHandler)  # Logs to console
        self.logger.addHandler(self.generalLogHandler)    
        self.logger.addHandler(self.errorLogHandler)
        
        self.SetupSQL()
                
        #!TESTING
        self.logger.debug(f"TEST PORT : {testPort}")

        # Start listening for file transfer before registering with the server
        self.listenerSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listenerSocket.bind(('127.0.0.1', testPort)) 
        self.listenerSocket.listen(5)  # Up to 5 queued connections
        self.listenPort = self.listenerSocket.getsockname()[1]

        self.logger.info(f"Listening for incoming file transfer on port {self.listenPort}...")



    def SetupSQL(self):
        try:
            databaseConnection = sqlite3.connect(f'Peer{userCode}FileDatabse.db')
            cursor = databaseConnection.cursor()
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS fileNameTracker (
                fileID TEXT NOT NULL UNIQUE,
                fileUserName TEXT NOT NULL UNIQUE,
                fileName TEXT NOT NULL,
                fileExtension TEXT NOT NULL,
                fileSize INTEGER NOT NULL
            )
            ''') 
            
            databaseConnection.commit() 
            databaseConnection.close()
        except Exception as e:
            self.logger.error(f"Error {e} in SetupSQL", exc_info=True)

    def connectToServer(self):
        try:
            self.logger.info(f"Connecting to server at {self.signalingServerHost}:{self.signalingServerPort}")
            self.peerSocket.connect((self.signalingServerHost, self.signalingServerPort))

            # Send peer info with dynamically assigned port
            myInfo = {'ip': "127.0.0.1", 'port': self.listenPort, 'name': self.name, 'joinType': 'receiver','userCode' : userCode}
            self.logger.info(f"Sending peer info: {myInfo}")
            self.peerSocket.send(json.dumps(myInfo).encode())

            # Receive the list of known peers
            peers = self.peerSocket.recv(1024).decode()
            self.logger.debug(f"Raw received peer list (string): {peers}")  # Debugging step

            peers = json.loads(peers)  # Convert the JSON string into a Python dictionary
            self.logger.debug(f"Processed peer list: {peers}")
            for peer in peers:
                self.logger.debug(f"Connected peer's name: {(peers[peer])['name']}")

            self.peerSocket.close()
            return peers
        except Exception as e:
            self.logger.error(f"Error connecting to server: {e}", exc_info=True)

    def SendFile(self, filePath, fileNameUser):
        try:
            serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            serverSocket.connect((self.signalingServerHost, self.signalingServerPort))
            
            chunkedData = []
            
            fileSize = os.path.getsize(filePath)
            totalChunkCount = fileSize // 1024
            if(fileSize % 1024 != 0):
                totalChunkCount += 1
            
            self.logger.info(f"FILE SIZE {fileSize}")
            
            #Setting file extension
            filePathBase = os.path.basename(filePath)
            fileName, fileExtension = os.path.splitext(filePathBase)
            
            #Sending request to send files
            serverSocket.send(json.dumps({"type" : "uploadPing", "userCode" : userCode}).encode())
            response = json.loads(serverSocket.recv(64).decode())
            if (response) and (response["type"] == "uploadPong") and (response["status"] == "accept"):
                #We can send files

                serverSocket.send(str(totalChunkCount).zfill(8).encode())            
                
                with open(filePath,"rb") as fileHandle:
                    for chunkIndex in range(totalChunkCount):
                            chunk = fileHandle.read(1024)
                            
                            #Padding
                            if(len(chunk) < 1024):
                                padder = padding.PKCS7(128).padder()
                                chunk = padder.update(chunk)  # Apply the padding
                                chunk += padder.finalize()  # Finalize padding to make the chunk a multiple of 128 bytes
                                while len(chunk) < 1024:
                                    chunk += b"\0" * (1024 - len(chunk))  # This is just to get to 1024 bytes
                            
                            chunkedData.append(chunk)
                            
                            # Send chunk number
                            serverSocket.send(str(chunkIndex).zfill(8).encode())  # Send chunk number
                            serverSocket.send(chunk)  # Send data chunk
                            self.logger.info(f"Sent chunk {chunkIndex + 1}/{totalChunkCount} ({1024} bytes)")

                #Receive fileID
                fileIDMessage = json.loads(serverSocket.recv(64).decode().rstrip("\0"))
                self.logger.debug(f"FILE ID MESSAGE : {fileIDMessage}")
                
                databaseConnection = sqlite3.connect(f'Peer{userCode}FileDatabse.db')
                cursor = databaseConnection.cursor()
                
                cursor.execute("INSERT INTO fileNameTracker (fileID, fileUserName, fileName, fileExtension, fileSize) VALUES (?, ?, ?, ?, ?)", (fileIDMessage["fileID"], fileNameUser, fileName, fileExtension, os.path.getsize(filePath)))
                databaseConnection.commit()
                databaseConnection.close()
                
                self.logger.debug("UPDATED DATABASE")
                
            serverSocket.close()
        except Exception as e:
            self.logger.error(f"Error {e} in SendFile", exc_info=True)
    
    def ReceiveReturnFile(self, fileID, connectionSocket):
        try:
            #Creating file
            databaseConn = sqlite3.connect(f'Peer{userCode}FileDatabse.db')
            cursor = databaseConn.cursor()
            cursor.execute("SELECT * FROM fileNameTracker WHERE fileID = ?", (fileID,))
            row = cursor.fetchone()
            fileOutputName = row[2] + row[3]
            fileOutputPath = r"C:\Users\iniga\OneDrive\Programming\P2P Storage\File Output"
            
            with open(f"{fileOutputPath}/{fileOutputName}", "w+b") as fileHandle:
                fileHandle.truncate(row[4])
                #Receiving data
                for i in range(math.ceil(row[4] / 1024)):
                    details = connectionSocket.recv(64).strip(b"\0")
                    detailsDecoded = json.loads(details.decode().strip())
                    
                    self.logger.debug(f"detailsDecoded = {detailsDecoded}")
                    
                    chunkData = connectionSocket.recv(detailsDecoded["chunkLength"])
                    fileHandle.seek(detailsDecoded["chunkIndex"] * 1024)
                    fileHandle.write(chunkData)
        except Exception as e:
            self.logger.error(f"Error {e} in ReceiveReturnFile", exc_info=True)
                
    
    def WaitToReceiveChunks(self):
        while True:
            try:
                #Receiving request
                peerSocket,_ = self.listenerSocket.accept()
                self.logger.info(f"Connecting to {self.signalingServerHost}:{self.signalingServerPort}")
                chunkSendRequest = peerSocket.recv(64)
                self.logger.info(f"RECEIVED RAW {chunkSendRequest}")
                chunkSendRequest = chunkSendRequest.rstrip(b"\0")
                if(chunkSendRequest == b""):
                    continue
                chunkSendRequestDecoded = json.loads(chunkSendRequest.decode())
                self.logger.info(f"RECEIVED {chunkSendRequestDecoded}")
            
                if(chunkSendRequestDecoded["type"] == "chunkStoreRequest"):
                    #Sending confirmation back
                    returnMessage = {"type" : "chunkStoreResponseAccept"}
                    peerSocket.send(json.dumps(returnMessage).encode())
                    
                    self.ReceiveChunk(peerSocket)
                elif(chunkSendRequestDecoded["type"] == "heartbeatPing"):
                    returnMessage = {"type" : "heartbeatPingConfirmation"}
                    peerSocket.send(json.dumps(returnMessage).encode())
                elif(chunkSendRequestDecoded["type"] == "fileReturnRequest"):
                    returnMessage = {"type" : "fileReturnRequestAccept"}
                    peerSocket.send(json.dumps(returnMessage).encode())
                    self.ReceiveReturnFile(chunkSendRequestDecoded["fileID"], peerSocket)
                elif(chunkSendRequestDecoded["type"] == "deleteFileServerRequest"):
                    
                    returnMessage = {"type" : "deleteFileServerRequestAccept"}
                    peerSocket.send(json.dumps(returnMessage).encode())
                    self.DeleteChunk(peerSocket)
                elif(chunkSendRequestDecoded["type"] == "chunkReceiveRequest"):
                    #Sending confirmation back
                    returnMessage = {"type" : "chunkReceiveRequestAccept"}
                    peerSocket.send(json.dumps(returnMessage).encode())
                    
                    #Receiving chunk details
                    chunkDetails = peerSocket.recv(128)
                    self.logger.debug(f"RAW JSON : {chunkDetails.decode()}")
                    chunkDetailsDecoded = json.loads(chunkDetails.decode())
                    self.logger.debug(f"JSON : {chunkDetailsDecoded}")
                    chunkIndex = chunkDetailsDecoded["chunkIndex"]
                    fileID = chunkDetailsDecoded["fileID"]
                    targetUserCode = chunkDetailsDecoded["userCode"]
                    
                    #Finding chunk
                    folderStoragePath = r"C:/Users/iniga/OneDrive/Programming/P2P Storage/Received Files"
                    
                    #!TEMP - REMOVE USER CODE AT START
                    with open(f"{folderStoragePath}/{userCode}--CODE-{targetUserCode}--INDEX-{chunkIndex}--FILEID-{fileID}.bin", "rb") as fileHandle:
                        chunkData = fileHandle.read()
                        peerSocket.send(chunkData)
                    

            except Exception as e:
                self.logger.error(f"RECEIEVED ERROR {e} IN WaitToReceiveChunks", exc_info=True)
            finally:
                peerSocket.close()
        
    def DeleteChunk(self, connectionSocket):
        try:
            messageRaw = connectionSocket.recv(64).strip(b"\0").decode()
            self.logger.debug(f"messageRaw in DeleteChunk : {messageRaw}")
            message = json.loads(messageRaw)
            fileID = message["fileID"]
            chunkIndex = message["chunkIndex"]
            
            #Finding file
            folderPath = r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Received Files"
            files = [f for f in os.listdir(folderPath) if os.path.isfile(os.path.join(folderPath, f))]
            
            for file in files[:]:
                if(f"FILEID-{fileID}" in file) and (f"INDEX-{chunkIndex}" in file):
                    #Delete file
                    fileSize = os.path.getsize(f"{folderPath}/{file}")
                    os.remove(f"{folderPath}/{file}")
                    
                    #Sending data
                    sizeMessage = {"size" : fileSize}
                    connectionSocket.send(json.dumps(sizeMessage).encode())
                    
        except Exception as e:
            self.logger.error(f"Error {e} in DeleteChunk", exc_info=True)
    
    def ReceiveChunk(self, peerSocket):
        try:
            #Chunk data
            chunkData = peerSocket.recv(128).decode()
            chunkData = chunkData.strip("\0")
            chunkData = json.loads(chunkData)
            self.logger.debug(f"CHUNK DATA : {chunkData}")
            
            #Receiving chunk
            chunk = peerSocket.recv(1024)
            
            #Saving chunk data
            folderWritePath = r"C:/Users/iniga/OneDrive/Programming/P2P Storage/Received Files"
            
            #!REMOVE THE USERCODE PHRASE - FOR TESTING
            with open(f'{folderWritePath}/{userCode}--CODE-{chunkData["userCode"]}--INDEX-{chunkData["chunkIndex"]}--FILEID-{chunkData["fileID"]}.bin', "wb") as fileHandle:
                fileHandle.write(chunk) 
        except Exception as e:
                   self.logger.error(f"Error {e} in RecieveChunk", exc_info=True)
    
    
    def DisplayFiles(self):
        try:
            conn = sqlite3.connect(f"Peer{userCode}FileDatabse.db")
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM fileNameTracker")
            rows = cursor.fetchall()
            print("=" * 30)
            print("CURRENT FILES : ")
            for row in rows:
                print(row[1])
            print("=" * 30)
            conn.close()
        except Exception as e:
            self.logger.error(f"Error {e} in DisplayFiles", exc_info=True)
    
    def RequestFile(self, fileUserName):
        try:
            #Finding actual code in database
            conn = sqlite3.connect(f"Peer{userCode}FileDatabse.db")
            cursor = conn.cursor()
            cursor.execute("SELECT fileID FROM fileNameTracker WHERE fileUserName = ?", (fileUserName,))
            fileID = cursor.fetchone()[0]
            conn.close()
            
            #Sending request
            serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            serverSocket.connect((self.signalingServerHost, self.signalingServerPort))
            serverSocket.send(json.dumps({"type" : "requestPing", "fileID" : fileID}).encode())
            conn.close()
        except Exception as e:
            self.logger.error(f"Error {e} in RequestFile", exc_info=True)
    
    
    def DeleteFile(self, fileUserName):
        try:
            #Finding actual code in database
            conn = sqlite3.connect(f"Peer{userCode}FileDatabse.db")
            cursor = conn.cursor()
            cursor.execute("SELECT fileID FROM fileNameTracker WHERE fileUserName = ?", (fileUserName,))
            fileID = cursor.fetchone()[0]
            
            #Removing from database
            cursor.execute("DELETE FROM fileNameTracker WHERE fileID = ?", (fileID,))
            conn.commit()
            conn.close()
            
            #Sending request
            serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            serverSocket.connect((self.signalingServerHost, self.signalingServerPort))
            serverSocket.send(json.dumps({"type" : "deleteRequest", "fileID" : fileID}).encode())
            conn.close()
        except Exception as e:
            self.logger.error(f"Error {e} in DeleteFile", exc_info=True)
    
if __name__ == '__main__':
    peer = Peer(name=deviceName)
    peers = peer.connectToServer()
    threading.Thread(target = peer.WaitToReceiveChunks, daemon=True).start()
    while(True):
        stateInput = input("(S)end, (W)ait, (D)isplay, (E)rase or (R)equest? : ")
        if(stateInput.strip().upper() == "S"):  
            peer.SendFile("TestFile.txt", "TestFile1")
            print("File Sent!")
        elif(stateInput.strip().upper() == "D"):
            peer.DisplayFiles()
        elif(stateInput.strip().upper() == "R"):
            peer.RequestFile(input("What is the file name you are requesting? : "))
        elif(stateInput.strip().upper() == "E"):
            peer.DeleteFile(input("What is the file name you want to delete : "))