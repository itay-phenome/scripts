@echo off
:: Remove all existing network folder mappings
echo Removing existing network mappings...
net use * /delete /yes

:: Map the specified network folder to Z: drive
echo Mapping network folder...
net use Z: \\52.209.113.208\tom /user:52.209.113.205\tom tom123

echo Network drive mapping completed.