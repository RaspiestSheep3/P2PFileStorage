import socket
import json
import threading
from datetime import datetime
import os
from cryptography.hazmat.primitives import padding, hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import logging
import colorlog
import sqlite3
import math
from dotenv import load_dotenv
from flask import Flask, jsonify, Response, request
from flask_cors import CORS
import requests

waitingForFiles = True
deviceName = datetime.now().strftime("%H:%M:%S")
userCode = input("USER CODE : ") #!TEMP
testPort = int(input("TARGET PORT : ")) #!TEMP
password = input("PASSWORD : ") #!TEMP
frontendPort = int(input("FRONTEND PORT : ")) #!TEMP

#!TEMP
if(input("SHOULD DELETE FILES? : ").strip().upper() == "Y"):
    if(os.path.exists(f"Peer{userCode}General.log")):
        os.remove(f"Peer{userCode}General.log")
    if(os.path.exists(f"Peer{userCode}Errors.log")):
        os.remove(f"Peer{userCode}Errors.log")
    if(os.path.exists(f"Peer{userCode}FileDatabse.db")):
        os.remove(f"Peer{userCode}FileDatabse.db")

#Setting up .env
load_dotenv(dotenv_path=".env.peer")
sslCertificateLocation = os.getenv("SSL_CERTIFICATE_LOCATION")

class Peer:
    def __init__(self, signalingServerHost='127.0.0.1', signalingServerPort=12345, name=""):
        self.signalingServerHost = signalingServerHost
        self.signalingServerPort = signalingServerPort
        self.name = name
        self.peerSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.chunkSize = None

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
        
        #Setting up .env and json 
        self.encryptionIterations = int(os.getenv("ENCRYPTION_ITERATIONS"))
        
        self.encryptionSalt = userCode.encode("utf-8")
        self.kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,                      # 16 bytes = AES-128, use 32 for AES-256
            salt=self.encryptionSalt,
            iterations=self.encryptionIterations,
            backend=default_backend()
        )
        self.key = self.kdf.derive(password.encode("utf-8"))
        self.aesgcm = AESGCM(self.key)
    
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
                fileSize INTEGER NOT NULL,
                nonceList BLOB NOT NULL
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

            serverInfo = json.loads(self.peerSocket.recv(128).rstrip(b"\0").decode())
            self.logger.debug(f"serverInfo : {serverInfo}")
            self.chunkSize = serverInfo["chunkSize"]
            
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
            
            #Setting file extension
            filePathBase = os.path.basename(filePath)
            fileName, fileExtension = os.path.splitext(filePathBase)
            
            #Sending request to send files
            serverSocket.send(json.dumps({"type" : "uploadPing", "userCode" : userCode}).encode())
            response = json.loads(serverSocket.recv(64).decode())
            if (response) and (response["type"] == "uploadPong") and (response["status"] == "accept"):
                #We can send files      
                
                #Making a temporary copy with the encrypted data
                
                nonceList = []
                ciphertextFilePath = (filePath.replace(fileExtension, "")) + "Cipher.bin"
                
                with open(filePath, "rb") as fileHandle:
                    with open(ciphertextFilePath, "wb") as fileHandleWrite:
                        for chunkIndex in range(math.ceil(os.path.getsize(filePath)/(1024 * 128))):
                            chunk = fileHandle.read(1024 * 128)
                            nonce = os.urandom(12)
                            ciphertext = self.aesgcm.encrypt(nonce, chunk, None)
                            fileHandleWrite.write(ciphertext)
                            nonceList.append(nonce)

                totalChunkCount = os.path.getsize(ciphertextFilePath) // self.chunkSize
                if(os.path.getsize(ciphertextFilePath) % self.chunkSize != 0):
                    totalChunkCount += 1
                
                serverSocket.send(str(totalChunkCount).zfill(8).encode())      

                with open(ciphertextFilePath,"rb") as fileHandle:
                    for chunkIndex in range(totalChunkCount):
                            chunk = fileHandle.read(self.chunkSize)
                            
                            #Padding
                            if(len(chunk) < self.chunkSize):
                                padder = padding.PKCS7(128).padder()
                                chunk = padder.update(chunk)  # Apply the padding
                                chunk += padder.finalize()  # Finalize padding to make the chunk a multiple of 128 bytes
                                while len(chunk) < self.chunkSize:
                                    chunk += b"\0" * (self.chunkSize - len(chunk))  # This is just to get to 1024 bytes
                            
                            chunkedData.append(chunk)
                            
                            # Send chunk number
                            serverSocket.send(str(chunkIndex).zfill(8).encode())  # Send chunk number
                            serverSocket.send(chunk)  # Send data chunk
                            self.logger.info(f"Sent chunk {chunkIndex + 1}/{totalChunkCount} ({self.chunkSize} bytes)")

                #Receive fileID
                fileIDMessage = json.loads(serverSocket.recv(64).decode().rstrip("\0"))
                self.logger.debug(f"FILE ID MESSAGE : {fileIDMessage}")
                
                databaseConnection = sqlite3.connect(f'Peer{userCode}FileDatabse.db')
                cursor = databaseConnection.cursor()
                
                cursor.execute("INSERT INTO fileNameTracker (fileID, fileUserName, fileName, fileExtension, fileSize, nonceList) VALUES (?, ?, ?, ?, ?, ?)", (fileIDMessage["fileID"], fileNameUser, fileName, fileExtension, os.path.getsize(ciphertextFilePath), b",".join(nonceList)))
                databaseConnection.commit()
                databaseConnection.close()
                
                self.logger.debug("UPDATED DATABASE")
                
                #Killing the cipher file
                os.remove(ciphertextFilePath)
                
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
            fileOutputNameCipher = row[2] + "Cipher.bin"
            fileOutputName = row[2] + row[3]
            fileOutputPath = os.getenv("FILE_OUTPUT_PATH")
            
            with open(f"{fileOutputPath}/{fileOutputNameCipher}", "wb") as fileHandle:
                fileHandle.truncate(row[4])
                #Receiving data
                self.logger.debug(f"ITERATION AMOUNT IN RRF : {math.ceil(row[4] / self.chunkSize)}, {row[4]}")
                for i in range(math.ceil(row[4] / self.chunkSize)):
                    details = connectionSocket.recv(64).strip(b"\0")
                    detailsDecoded = json.loads(details.decode().strip())
                    
                    self.logger.debug(f"detailsDecoded = {detailsDecoded}")
                    
                    chunkData = connectionSocket.recv(detailsDecoded["chunkLength"])
                    fileHandle.seek(detailsDecoded["chunkIndex"] * self.chunkSize)
                    fileHandle.write(chunkData)
            
            #Decrypting file
            with open(f"{fileOutputPath}/{fileOutputNameCipher}", "rb") as fileHandle:
                with open(f"{fileOutputPath}/{fileOutputName}", "wb") as fileHandleWrite:
                    for chunkIndex in range(math.ceil(os.path.getsize(f"{fileOutputPath}/{fileOutputNameCipher}") / (1024 * 128))):
                        chunk = fileHandle.read(1024 * 128 + 16) #+16 for some extra data for AES
                        nonce = row[5].split(b",")[chunkIndex]
                        decryptedChunk = self.aesgcm.decrypt(nonce, chunk, None)
                        fileHandleWrite.write(decryptedChunk)  
            
            #Deleting cipher file
            self.logger.debug(f"Deleting file {fileOutputPath}/{fileOutputNameCipher}")
            os.remove(f"{fileOutputPath}/{fileOutputNameCipher}")
            
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
                elif (chunkSendRequestDecoded["type"] == "serverShutdown"):
                    self.logger.warning("SERVER SHUTTING DOWN")
                    return
                    
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
                    folderStoragePath = os.getenv("FILE_STORAGE_PATH")
                    
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
            folderPath = folderStoragePath = os.getenv("FILE_STORAGE_PATH")
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
            chunk = peerSocket.recv(self.chunkSize)
            
            #Saving chunk data
            folderWritePath = os.getenv("FILE_STORAGE_PATH")
            
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
    
    def GetFileList(self):
        try:
            conn = sqlite3.connect(f"Peer{userCode}FileDatabse.db")
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM fileNameTracker")
            rows = cursor.fetchall()
            fileList = []
            for row in rows:
                fileList.append({"fileID" : row[0], "fileUserName" : row[1], "fileName" : row[2], "fileExtension" : row[3], "fileSize" : row[4]})
            conn.close()
            return fileList
        except Exception as e:
            self.logger.error(f"Error {e} in GetFileList", exc_info=True)

#FLASK
app = Flask(__name__)
CORS(app)  # Allows cross-origin requests

themesJSONLocation = os.getenv("THEME_JSON_LOCATION")
loginPreferencesJSONLocation = os.getenv("LOGIN_PREFERENCE_JSON_LOCATION")
uploadFileBufferFolder = os.getenv("UPLOAD_BUFFER_LOCATION")

loginPreferencesJSONLock = threading.Lock()

@app.route('/api/Post/SendLoginRequest', methods=['POST'])
def SendLoginRequest():
    try:
        data = request.json
        peer.logger.debug(f"Received data SendLoginRequest: {data}")
        
        # Check if the request contains the expected keys
        if 'username' not in data or 'password' not in data:
            return jsonify({"error": "Invalid request"}), 400
        
        response = requests.post(
            "https://localhost:5000/LoginRequest",
            json = data,
            verify=sslCertificateLocation + "/cert.pem"
        )
        
        print(f"RESPONSE JSON {response.json()}, {type(response.json)}")
        return jsonify({"status": response.json()["status"]})
    
    except Exception as e:
        peer.logger.error(f"Error {e} in SendLoginRequest", exc_info=True)
        return jsonify({"Unexpected error - check logs"}), 500

@app.route('/api/GetFiles', methods=['GET'])
def GetFiles():
    try:
        data = peer.GetFileList()
        return jsonify(data) 
    
    except Exception as e:
        peer.logger.error(f"Error {e} in GetFiles", exc_info=True)
        return jsonify({"Unexpected error - check logs"}), 500

@app.route('/api/GetThemes', methods=['GET'])
def ReturnThemeJSON():
    try:
        with open(themesJSONLocation, 'r') as file:
            data = json.load(file)
        return jsonify(data) 
    
    except FileNotFoundError:
        return jsonify({"error": "Themes.json not found"}), 404
    
    except json.JSONDecodeError:
        return jsonify({"error": "Themes.json is not valid JSON"}), 500

@app.route('/api/Post/CreateAccount', methods=['POST'])
def CreateAccount():
    try:
        data = request.json
        peer.logger.debug(f"Received data CreateAccount: {data}")
        
        # Check if the request contains the expected keys
        if 'username' not in data or 'password' not in data:
            return jsonify({"error": "Invalid request"}), 400
        
        response = requests.post(
            "https://localhost:5000/AccountCreationRequest",
            json = data,
            verify=sslCertificateLocation + "/cert.pem"
        )
        
        print(f"RESPONSE JSON {response.json()}, {type(response.json)}")
        return jsonify({"status": response.json()["status"]})
    
    except Exception as e:
        peer.logger.error(f"Error {e} in CreateAccount", exc_info=True)
        return jsonify({"Unexpected error - check logs"}), 500

@app.route('/api/Post/ChangeThemePreference', methods=['POST'])
def ChangeThemePreferences():
    content = request.json  # Get JSON from the request body
    print("Received:", content)
    #update logging software
    newColour = content["colour"]
    
    #Updating jsons
    UpdateJSON("Theme", newColour, loginPreferencesJSONLocation, "Preference")
    return jsonify({"message": "Data received!", "received": content})

def UpdateJSON(key, value, path, lockType):
    lockTypeDict = {
        "Preference" : loginPreferencesJSONLock,
    }
    lockType = lockTypeDict[lockType]
    with lockType:
        with open(path, "r") as fileHandle:
            data = json.load(fileHandle)
            data[key] = value
        with open(path, "w") as fileHandle:
            json.dump(data, fileHandle, indent=4)

@app.route('/api/Preferences', methods=['GET'])
def ReturnPreferences():
    try:
        with open(loginPreferencesJSONLocation, 'r') as file:
            data = json.load(file)
        return jsonify(data) 
    
    except FileNotFoundError:
        return jsonify({"error": "Preferences.json not found"}), 404
    
    except json.JSONDecodeError:
        return jsonify({"error": "Preferences.json is not valid JSON"}), 500

@app.route('/api/Post/UploadFile', methods=['POST'])
def Upload():
    uploadedFile = request.files['file']  # 'file' must match the FormData key

    # You can read the content
    content = uploadedFile.read()
    filename = uploadedFile.filename
    basename, _ = os.path.splitext(uploadedFile.filename)
    
    print(f"RECEIVED A FILE : {filename}")
    
    #Creating a buffer file
    with open(uploadFileBufferFolder + filename, "wb") as fileHandle:
        fileHandle.write(content)
    
    peer.SendFile(uploadFileBufferFolder+filename, basename)
    
    #Deleting the buffer file
    os.remove(uploadFileBufferFolder + filename)

    return jsonify({"status" : "received"}), 500

@app.route('/api/Post/DeleteFile', methods=['POST'])
def DeleteFile():
    content = request.json  # Get JSON from the request body
    print("DELETING:", content)

    filename, _ = os.path.splitext(content["filename"])
    
    peer.DeleteFile(filename)
    
    return jsonify({"status" : "success"})

@app.route('/api/Post/RequestFile', methods=['POST'])
def RequestFile():
    content = request.json  # Get JSON from the request body
    print("REQUESTING:", content)

    filename, _ = os.path.splitext(content["filename"])
    
    peer.RequestFile(filename)
    
    return jsonify({"status" : "success"})

if __name__ == '__main__':
    
    peer = Peer(name=deviceName)
    peers = peer.connectToServer()
    threading.Thread(target = peer.WaitToReceiveChunks, daemon=True).start()
    #Starting website
    threading.Thread(target = app.run, kwargs={"port": int(frontendPort), "debug": False}).start()
    while(True):
        stateInput = input("(S)end, (W)ait, (D)isplay, (E)rase or (R)equest? : ")
        if(stateInput.strip().upper() == "S"):  
            peer.SendFile("TestFile.txt", "TestFile")
            print("File Sent!")
        elif(stateInput.strip().upper() == "D"):
            peer.DisplayFiles()
        elif(stateInput.strip().upper() == "R"):
            peer.RequestFile(input("What is the file name you are requesting? : "))
        elif(stateInput.strip().upper() == "E"):
            peer.DeleteFile(input("What is the file name you want to delete : "))
    
    