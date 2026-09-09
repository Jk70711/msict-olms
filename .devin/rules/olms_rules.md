# OLMS Project Rules

## Django Management Commands
When running Django management commands in /home/jonas/PROJECT/OLMS, always use the virtual environment Python:
```bash
./olmsvenv/bin/python manage.py <command>
```
The system Python lacks python-decouple and will fail with ModuleNotFoundError: decouple.

## Change Strategy
Make surgical, integration-safe updates:
- Modify only areas directly related to new additions
- Avoid removing or breaking existing logic
- Preserve existing functionality when adding features
