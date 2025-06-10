#!/bin/bash
ls -la /shared
cd ~
pwd
source .bashrc
echo "GDAL version:"
gdal-config --version
python --version
echo "GDAL DATA:"
echo $GDAL_DATA
echo "PROJ_LIB"
echo $PROJ_LIB
cd /app
echo "{'s1_ascending': '$1', 's1_descending': '$2', 'start':$3, 'end':$4, 'outputArtifactName': '$5'}"
export PROJ_LIB=/home/nonroot/miniforge3/share/proj
export GDAL_DATA=/home/nonroot/miniforge3/share/gdal
#export PATH="/home/nonroot/miniforge3/snap/.snap/auxdata/gdal/gdal-3-0-0/bin/:$PATH"
echo "GDAL DATA AFTER EXPORT:"
echo $GDAL_DATA
echo "PROJ_LIB AFTER EXPORT"
echo $PROJ_LIB
python main.py "{'s1_ascending': '$1', 's1_descending': '$2', 'start':$3, 'end':$4, 'outputArtifactName': '$5'}"
exit