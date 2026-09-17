# 1-Tap iOS Shortcut Setup Guide: Pennyworth to Financial Tracker

This guide explains how to set up an Apple Shortcut on your iPhone so you can export transactions from Pennyworth and update your live Financial Tracker on Render (`https://financial-tracker-aoq9.onrender.com`) in **2 seconds directly from your phone**.

---

## How It Works in 2 Steps

1. In **Pennyworth**, go to **Settings / Export** and tap **Export CSV** (or Share).
2. In the iOS Share Sheet, tap **"Sync to Finance Tracker"**.
3. The shortcut POSTs the CSV file directly to your Render API.
4. You receive a banner notification: **"✅ Imported N new transactions! Ledger updated."**

---

## Step-by-Step Apple Shortcut Setup

### Step 1: Open the Shortcuts App on iPhone
1. Open the built-in **Shortcuts** app on iOS.
2. Tap the **`+`** (plus) icon in the top right to create a new shortcut.
3. Tap the title at the top (e.g. "New Shortcut") and rename it to **`Sync to Finance Tracker`**.
4. Choose an icon (e.g. dollar sign or chart with blue color).

### Step 2: Enable "Show in Share Sheet"
1. Tap the **`ⓘ` (Information)** icon at the bottom.
2. Toggle ON **"Show in Share Sheet"**.
3. Under **"Share Sheet Types"**, select **Files** and **Text**.
4. Tap **Done**.

### Step 3: Add Shortcut Actions

Add the following 3 actions:

#### Action 1: `Get Contents of URL`
- Tap **Add Action** and search for **"Get Contents of URL"**.
- Set the **URL** to:
  ```
  https://financial-tracker-aoq9.onrender.com/api/import?token=2026
  ```
  *(If you changed your `APP_PASSWORD`, use that value instead of 2026).*
- Tap the disclosure arrow `>` on the action to expand advanced options:
  - **Method**: Change from `GET` to **`POST`**.
  - **Headers**:
    - Tap **Add new header**.
    - Key: `Content-Type`
    - Value: `text/plain`
  - **Request Body**:
    - Change from `JSON` to **`File`**.
    - Set File to: **`Shortcut Input`** (select it from the variable bar).

#### Action 2: `Get Dictionary Value` (Optional, for rich summary)
- Tap **Add Action** -> search **"Get Dictionary from Input"**.
  - Input: `Contents of URL`.
- Add Action -> **"Get Value for `message` in `Dictionary`"**.

#### Action 3: `Show Notification`
- Tap **Add Action** -> search **"Show Notification"**.
- Set the notification text to:
  ```
  ✅ Finance Tracker: [Dictionary Value]
  ```
- Toggle OFF "Play Sound" (optional).

---

## Alternative: Siri Quick Add Shortcut (For Single Expenses)

You can also create a voice/widget shortcut called **"Add Expense"**:
1. Action: **Ask for Input**: "How much did you spend?" (Number)
2. Action: **Ask for Input**: "What was it for?" (Text)
3. Action: **Get Contents of URL**:
   - URL: `https://financial-tracker-aoq9.onrender.com/api/transactions/quick?token=2026`
   - Method: `POST`
   - Body: `JSON`
     - `amount`: `[Provided Number]`
     - `description`: `[Provided Text]`
     - `category`: `General`
     - `account`: `Mobile Money`
4. Action: **Show Notification**: "Logged UGX [Amount] for [Description]".

---

## Testing Your Shortcut
1. Open Pennyworth -> tap Export CSV.
2. Select your new shortcut from the Share Sheet.
3. Check your live dashboard at `https://financial-tracker-aoq9.onrender.com`.
4. Your new transactions and metrics will be updated instantly!
