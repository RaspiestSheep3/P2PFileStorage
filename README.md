# Heimdall - A P2P Storage App

## Overview
Heimdall is an open-source **Peer-based Storage App** that uses other users to securely store data as opposed to using opaque cloud servers. The project uses powerful encryption to ensure data is data is hidden from everyone except you, even server owners.  

---

## Features

- **End-to-End Encryption**  
  Messages and file transfers are encrypted using AES-256 to ensure maximum security and privacy

- **Secure File Transfers**  
  Files are encrypted before being sent and only decrypted upon receipt by the original owner

- **Multi File Type Support** 
  All file types are supported and the file extension is automatically maintained for maximum ease of use

- **File Return Buffering** 
  Servers can buffer requested data when the requester goes offline to ensure all stored data can easily be obtained upon request

- **Easy UI**  
  The UI for both Server and Peer is easy to understand even without a background in CS whilst still providing valuable data and insights

- **HTML Integration**  
  Clean and responsive interface with real-time updates powered by the backend Flask API

---

## Architecture Overview

- **Python** is used to form the backend of the project
    - The **socket** module is used to handle connections using the **TCP** protocol
    - **AES** is used through the **cryptography** module, with **DHE** being used to securely generate and share the key
    - **SQL** is used to track users and messages using **sqlite3**
    - Logging is done through the **logging** module, which allows for different warning levels to avoid clutter 
    - **Flask API** is used to provide a gateway for the frontend to render the project
- **HTML, CSS and Javascript** is used to provide a clear user display in a browser, eliminating the need for a specific app

---

## Learning Results

- This was my first big **networking** project, so I had to learn about **TCP** protocols and how to use the **socket module**

- This is also my first big **cybersecurity** project, so I learnt about common algorithms such as **AES** and **RSA** and their power for encrypting data

- I learnt how to use **SQL** and its power for database management

- I improved my **file management** skills and how to effectively achieve such a project efficently and with minimum redundancy

- I learnt about **multithreading** and how to safely utilise it to increase the efficency of an algorithm

- I learnt **HTML, CSS and JS** and how they can be used to display data in the browser 

--- 

## Future Improvements

- **TURN** implemenation to deal with NAT Traversal

- **Load Balancing** to avoid servers being overwhelmed if numerous requests are made

- **DoS protection** to stop malicious actors being able to disable the network by spamming it

## Images Showcase

**Login Page** 

![Login Screenshot](Display%20Images/Login%20Screenshot.png)

---

**Server Page**

![Server Screenshot](Display%20Images/Server%20Screenshot.png)

---

**Peer Page**

![Peer Screenshot](Display%20Images/Peer%20Screenshot.png)
