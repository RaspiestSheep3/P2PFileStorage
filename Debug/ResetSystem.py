import os
def ClearFolders(folders):
    for folder in folders:
        filesToRemove = os.listdir(folder)
        for fileToRemove in filesToRemove:
            os.remove(rf"{folder}\{fileToRemove}")