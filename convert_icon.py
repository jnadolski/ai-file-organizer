from PIL import Image

def convert_png_to_ico(png_path, ico_path):
    with Image.open(png_path) as img:
        img.save(ico_path, format='ICO', sizes=[(256, 256)])

if __name__ == "__main__":
    convert_png_to_ico("AI File Organizer (iOS Icon).png", "icon.ico")
