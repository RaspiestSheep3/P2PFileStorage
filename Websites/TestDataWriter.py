dayCounter = 19
month = 4
year = 2025
hourCounter = 22

import random

with open("TestData.csv", "w") as fileHandle:
    for i in range(30*24):
        timestamp = f"{hourCounter}--{dayCounter}-{month}-{year}"
        fileHandle.write(f"{timestamp},{random.randint(1,200)}\n")
        hourCounter += 1
        if(hourCounter > 23):
            hourCounter = 0
            dayCounter += 1
            if(dayCounter > 30):
                dayCounter = 1
                month += 1
    