%1@mshta vbscript:Execute("CreateObject(""Wscript.Shell"").Run """"""%~f0"""" :"",0:Close()")& exit/b

@echo off
cd /d "%~dp0"
python run.py
timeout 5 & echo Started!>"started.txt"