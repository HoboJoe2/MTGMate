from PyQt6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal, QMutex, QWaitCondition
from PyQt6 import uic
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from time import sleep, time
import csv
import requests
import numpy as np
import configparser
import os

class WorkerThread(QThread):
    progress_update = pyqtSignal(int)
    show_full_message = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.mutex = QMutex()
        self.wait_condition = QWaitCondition()

    #parses details from UI thread to worker thread
    def details(self, username, password, collection_path, spare_quantity, logBox, itemsPerSec):
        self.username = username
        self.password = password
        self.collection_path = collection_path
        self.spare_quantity = int(spare_quantity)
        self.logBox = logBox
        self.itemsPerSec = itemsPerSec
        self.collection = []
        self.cards = []
        self.log = []

    #code for updating the log box in the UI    
    def update_log_box(self, text):
        self.log.append(text)
        full_text = ''
        for entry in self.log:
            full_text += '\n' + entry
            
        self.logBox.setText(full_text)
        
    #code for resuming after maximum buylist was reached and emptied
    def resume(self):
        self.mutex.lock()
        self.wait_condition.wakeAll()
        self.mutex.unlock()

    #code that runs when worker thread is created    
    def run(self):
        #opens MTGMate site in chrome
        driver = webdriver.Chrome()
        driver.get("https://www.mtgmate.com.au/cards/buylist_search")
        self.update_log_box("Site opened.")
        sleep(2)

        #enter login details
        username_box = driver.find_element(By.ID, "user_email") 
        username_box.send_keys(self.username)
        password_box = driver.find_element(By.ID, "user_password") 
        password_box.send_keys(self.password)
        login_button = driver.find_element(By.NAME, "commit")
        login_button.click()
        
        sleep(1)
        #Run test card Black Lotus
        search_box = driver.find_element(
            By.XPATH, "//input[contains(@class, 'react-autosuggest__input')]")
        search_box.send_keys('Black Lotus')
        search_box.send_keys(Keys.RETURN)

        #adjusts maximum rows on page to 500
        try:
            rows_pp_box = driver.find_element(By.ID, "pagination-rows") 
            rows_pp_box.click()
            rows_500 = driver.find_element(By.XPATH, "//ul[@id='pagination-menu-list']/li[@data-value='500']")
            rows_500.is_displayed()
            rows_500.click()
        except:
            self.update_log_box('Could not increase rows per page, this may cause cards to be missed. Could be worth restarting')

        #Open manabox collection file
        with open(self.collection_path, 'r') as file:
            csv_reader = csv.reader(file)
            for row in csv_reader:
                self.collection.append(row)
            header = self.collection.pop(0)
        for row in self.collection:
            row = [str(row[0]), str(row[2]), str(row[4]), int(row[6]), str(row[8])]
            self.cards.append(row)
        self.update_log_box("Collection imported.")
            
        #begin checking buylist
        begin_time = time()
        first_card_added = False
        second_card_added = False
        self.update_log_box("Buylist checking begun.")
        buylist = [["Card Name", "Set Name", "Foil?", "Quantity", "Scryfall ID", "Colours"]]
        
        #begin searching cards 1 by 1
        for i, card in enumerate(self.cards):

            #checks to see if window is still open
            try:
                window_title = driver.title
            except:
                self.update_log_box('Chrome window seems to have been closed. Aborting search. You can try again.')
                break
            
            #updates progress bar
            self.progress_update.emit(int(((i+1)/len(self.cards))*100))
            try:
                self.itemsPerSec.setText(str(np.round((i+1)/(time()-begin_time),2)) + " items per second.")
            except:
                pass

            #checks to make sure buylist is not full
            try:
                num_in_buylist = int(driver.find_element(By.XPATH, '/html/body/nav/div[1]/ul[1]/li[5]/div[1]/span').text)
            except:
                if first_card_added == False:
                    num_in_buylist = 0
                else:
                    if second_card_added == True:
                        self.update_log_box('Unable to get the number of cards in buylist. Code will NOT automatically stop at 300 cards.')
                    else:
                        second_card_added = True
            
            #if it is full, create output CSV based on current buylist, and show message saying it is full.
            #restarts when OK is pushed and clears output.csv
            if num_in_buylist >= 300:
                with open("output.csv", mode="w", newline="") as file:
                    writer = csv.writer(file)
                    writer.writerows(buylist)
                self.update_log_box('Buylist maximum reached! Output CSV Created.')
                self.show_full_message.emit()
                self.mutex.lock()
                self.wait_condition.wait(self.mutex)
                self.mutex.unlock()
                buylist = [["Card Name", "Set Name", "Foil?", "Quantity", "Scryfall ID", "Colours"]]
                self.update_log_box('Checking continued.')

            #searches for card
            try:
                search_box = driver.find_element(
                    By.XPATH, "//input[contains(@class, 'react-autosuggest__input')]")
                search_box.send_keys(card[0])
                search_box.send_keys(Keys.RETURN)
            except:
                self.update_log_box(f'Issue searching for {card[0]}. Card skipped.')

            #actual meat of the check
            extra = False
            scryfall_checked = False
            try:
                #gets table from the page with card details
                table_body = driver.find_element(By.CLASS_NAME, "MuiTableBody-root")
                rows = table_body.find_elements(By.TAG_NAME, "tr")
                for row in rows:
                    #gets the card details for each row in the table, and cleans up the info
                    card_name = row.find_element(By.XPATH, ".//td[2]//span[@class='card-name']").text
                    if '(' in card_name:
                        extra = True
                    card_set = row.find_element(By.XPATH, ".//td[2]//span[@class='set-name font-italic text-muted']").text
                    try:
                        card_foil = row.find_element(By.XPATH, ".//td[2]//span[@class='badge badge-label']").text
                    except:
                        card_foil = "Normal"
                    card_quantity = int(row.find_element(By.XPATH, ".//td[4]//div").text[0])
                    card_price = float(row.find_element(By.XPATH, ".//td[5]//div").text[1:])

                    #if the card set matches, check scryfall if needed
                    if card_set == card[1]:
                        if extra == True and scryfall_checked == False:
                            try:
                                response = requests.get(f"https://api.scryfall.com/cards/{card[4]}")
                                if response.status_code == 200:
                                    card_data = response.json()
                                    
                                    #check for borderless
                                    if 'border_color' in card_data:
                                        if card_data['border_color'] == 'borderless':
                                            card[0] = card[0] + ' (Borderless)'
                                    
                                    #check for showcase
                                    if 'frame_effects' in card_data:
                                        if "showcase" in card_data['frame_effects']:
                                            card[0] = card[0] + ' (Showcase)'
                                            
                                        if "extendedart" in card_data['frame_effects']:
                                            card[0] = card[0] + ' (Extended Art)'
                                    
                                    #check for retro frame
                                    if 'frame' in card_data:
                                        if card_data['frame'] == '1997':
                                            card[0] = card[0] + ' (Retro Frame)'
                                scryfall_checked = True
                            except:
                                self.update_log_box(f'Issue when getting scryfall information for {card_name}. Card skipped.')
                        
                        #checks that other details match the card owned
                        if card_foil.lower() == card[2].lower():
                            if card[0] == card_name:
                                if card_quantity > 0:
                                    if card[3] - self.spare_quantity > 0:

                                        #makes sure to only add as many as requested by user
                                        if card_quantity < card[3]-self.spare_quantity:
                                            num_to_sell = card_quantity-self.spare_quantity
                                        else:
                                            num_to_sell = card[3]-self.spare_quantity

                                        #gets colour of card for output.csv
                                        response = requests.get(f"https://api.scryfall.com/cards/{card[4]}")
                                        if response.status_code == 200:
                                            card_data = response.json()
                                            color = card_data["colors"]
                                            card.append(color)
                                        buylist.append(card)
                                        
                                        #attempts to add x of the card to buylist
                                        try:
                                            sell_button = row.find_element(By.XPATH, ".//button[@class='btn btn-dark']")
                                            sell_button.click()
                                            button_dropdown = driver.find_element(By.XPATH, "//div[contains(@class, 'MuiGrid-root MuiGrid-container MuiGrid-spacing-xs-1')]")
                                            buttons = button_dropdown.find_elements(By.XPATH, ".//button[contains(@class, 'MuiButtonBase-root')]")
                                            for button in buttons:
                                                label = button.find_element(By.XPATH, ".//span[@class='MuiButton-label']").text
                                                if label == str(num_to_sell):
                                                    button.click()
                                            self.update_log_box(f'{num_to_sell}x {card_name} from {card_set} added to buylist at ${card_price}.')
                                            first_card_added = True
                                        except:
                                            self.update_log_box(f'Issue when adding {card_name} to buylist. Card skipped.')
            except:
                self.update_log_box(f'Issue when getting buylist information for {card[0]}. Card skipped.')
            self.update_log_box(f"{card[0]} checked.")
            sleep(0.1)
        
        #when complete, closes the chrome window
        self.update_log_box("\nBuylist adding complete.")
        driver.close()
        with open("output.csv", mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerows(buylist)

#saved details of user for later            
config = configparser.ConfigParser()

#main UI window code
class MainWindow(QMainWindow):
    
    def __init__(self):
        #creates window
        super().__init__()
        uic.loadUi('mainwindow.ui', self)
        self.resize(600, 450)
        self.setContentsMargins(20,20,20,20)

        #opens config file if it exists
        if os.path.exists("config.ini"):
            config.read("config.ini")
            self.usernameBox.setText(config["Info"]["username"])
            self.passwordBox.setText(config["Info"]["password"]) 
            self.collectionPath.setText(config["Info"]["path"]) 
            self.rememberBox.setChecked(True)

        #connects buttons
        self.goButton.pressed.connect(self.go)
        self.browseButton.pressed.connect(self.browse_file)
    
    #for collection file browsing
    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select a File", "", "CSV Files (*.csv);;All Files (*)")
        if file_path:
            self.collectionPath.setText(file_path)

    #creating maximum buylist message        
    def max_reached(self):
        msg_box = QMessageBox()
        msg_box.setWindowTitle("Maximum Buylist amount reached!")
        msg_box.setText("The maximum Buylist order size (300 cards) has been reached. Please submit this buylist order THEN push OK.")
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)

        #wait for OK to be pushed
        response = msg_box.exec()
        if response == QMessageBox.StandardButton.Ok:
            self.worker.resume()
    
    #runs the checking code when GO is pushed   
    def go(self):
        username = self.usernameBox.text()
        password = self.passwordBox.text()
        spare_quantity = self.spareBox.text()
        collection_path = self.collectionPath.text()

        #saves config file if requested
        config["Info"] = {"username": username, "password": password, "path": collection_path}
        if self.rememberBox.isChecked():
            with open("config.ini", "w") as configfile:
                config.write(configfile)

        #creates the worker thread and runs code with details given
        self.worker = WorkerThread()
        self.worker.details(username, password, collection_path, spare_quantity, self.logBox, self.itemsPerSec)
        self.worker.progress_update.connect(self.progressBar.setValue)
        self.worker.show_full_message.connect(self.max_reached)
        self.worker.start()
        
if not QApplication.instance():
    app = QApplication(sys.argv)
else:
    app = QApplication.instance()
if __name__ == "__main__":    
    app.setStyle('windowsvista')
    main = MainWindow()
    main.show()
    app.exec()