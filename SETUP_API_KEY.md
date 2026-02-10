# How to Set Up Your Gemini API Key

## Step 1: Get Your API Key

1. Visit: https://aistudio.google.com/app/apikey
2. Sign in with your Google account
3. Click **"Create API Key"** or **"Get API Key"**
4. Copy your API key (it will look like: `AIzaSy...`)

## Step 2: Add It to Your Project

### Method 1: Edit .env File (Recommended)

1. Open the `.env` file in your project folder
2. Replace the existing key with your own:
   ```
   GEMINI_API_KEY=your_actual_api_key_here
   ```
3. Save the file

### Method 2: Set Environment Variable (Windows)

**PowerShell:**
```powershell
$env:GEMINI_API_KEY="your_actual_api_key_here"
python app.py
```

**Command Prompt:**
```cmd
set GEMINI_API_KEY=your_actual_api_key_here
python app.py
```

### Method 3: Set Environment Variable (Permanent - Windows)

1. Press `Win + R`, type `sysdm.cpl`, press Enter
2. Go to **Advanced** tab → Click **Environment Variables**
3. Under **User variables**, click **New**
4. Variable name: `GEMINI_API_KEY`
5. Variable value: `your_actual_api_key_here`
6. Click **OK** on all dialogs
7. Restart your terminal/IDE

## Step 3: Restart the Application

After setting the key, restart your Flask application:

```bash
python app.py
```

## Verify It's Working

1. Open the application in your browser: http://localhost:5000
2. Upload an image and run analysis
3. If it works without the "Missing API Key" error, you're all set!

## Troubleshooting

- **Still seeing the error?** Make sure you:
  - Saved the `.env` file
  - Restarted the Flask server after changing the key
  - Used the correct variable name: `GEMINI_API_KEY`
  - Didn't include quotes around the key in the `.env` file

- **Key not working?** Check:
  - The key is correct (no extra spaces)
  - Your Google account has API access enabled
  - You have sufficient API quota

## Security Note

⚠️ **Never commit your `.env` file to version control!** It should already be in `.gitignore`.

