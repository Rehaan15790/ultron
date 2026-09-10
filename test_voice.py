import asyncio
import edge_tts

async def speak():
    # "en-US-GuyNeural" is a deep, calm male voice. 
    # We can change this to "en-US-JennyNeural" for a female voice later.
    communicate = edge_tts.Communicate("Greetings. I am ULTRON. Systems are online.", "en-US-GuyNeural")
    await communicate.save("ultron_voice.mp3")
    print("Success! Audio saved to ultron_voice.mp3")

asyncio.run(speak())