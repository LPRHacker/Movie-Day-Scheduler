import os
import django

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.devel')
django.setup()

from shifts.models import Cinema

def seed_cinemas():
    cinemas = [
        # MovieLand
        {"name": "MovieLand Netanya", "location_id": "1292"},
        {"name": "MovieLand Haifa", "location_id": "1290"},
        {"name": "MovieLand Karmiel", "location_id": "1291"},
        
        # Hot Cinema
        {"name": "Hot Cinema Petah Tikva", "location_id": "16"},
        {"name": "Hot Cinema Kfar Saba", "location_id": "1"},
        {"name": "Hot Cinema Ashdod", "location_id": "2"},
        {"name": "Hot Cinema Modiin", "location_id": "19"},
        
        # Cinema City
        {"name": "Cinema City Ayalon", "location_id": "1170"},
        {"name": "Cinema City Rishon LeZion", "location_id": "1175"},
        {"name": "Cinema City Glilot", "location_id": "1173"},
        {"name": "Cinema City Jerusalem", "location_id": "1160"},
        {"name": "Cinema City Hadera", "location_id": "1168"},
        
        # Yes Planet (Planet)
        {"name": "Yes Planet Ayalon", "location_id": "1025"},
        {"name": "Yes Planet Rishon LeZion", "location_id": "1072"},
        {"name": "Yes Planet Jerusalem", "location_id": "1073"},
        {"name": "Yes Planet Haifa", "location_id": "1070"},
        {"name": "Yes Planet Beer Sheva", "location_id": "1074"},
        
        # Theaters
        {"name": "תיאטרון בית ליסין", "location_id": None},
        {"name": "הבימה", "location_id": None},
        {"name": "הקאמרי", "location_id": None},
    ]
    
    for c_data in cinemas:
        obj, created = Cinema.objects.get_or_create(
            name=c_data["name"],
            defaults={"location_id": c_data.get("location_id")}
        )
        if created:
            print(f"Created cinema: {obj.name} ({obj.location_id})")
        else:
            # Update location_id if it's different
            if obj.location_id != c_data.get("location_id"):
                obj.location_id = c_data.get("location_id")
                obj.save()
                print(f"Updated cinema: {obj.name} with ID {obj.location_id}")
            else:
                print(f"Cinema already exists: {obj.name}")

if __name__ == "__main__":
    seed_cinemas()
