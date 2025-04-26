targetFileName = r"C:\Users\iniga\OneDrive\Programming\P2P Storage\Files To Send\userCode0000 0000 0000 0000--25_02_2025-18_48_26.bin"
with open(targetFileName, "rb") as fileHandleRead:
    with open("GeneratedImage.png", "wb") as fileHandleWrite:
        fileHandleWrite.write(fileHandleRead.read())