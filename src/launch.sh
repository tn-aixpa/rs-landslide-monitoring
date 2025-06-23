#!/bin/bash
ls -la /shared
cd ~
pwd
source .bashrc
export PATH="/home/nonroot/miniforge3/snap/bin:$PATH"
export PROJ_LIB=/home/nonroot/miniforge3/share/proj
export GDAL_DATA=/home/nonroot/miniforge3/share/gdal
export GDAL_DRIVER_PATH=/home/nonroot/miniforge3/lib/gdalplugins
export PROJ_DATA=/home/nonroot/miniforge3/share/proj
cd /app
echo "{'s1_ascending': '$1', 's1_descending': '$2', 'startDate':'$3', 'endDate':'$4', 'outputArtifactName': '$5'}"
#export PATH="/home/nonroot/miniforge3/snap/.snap/auxdata/gdal/gdal-3-0-0/bin/:$PATH"
echo "GDAL DATA AFTER EXPORT:"
echo $GDAL_DATA
echo "PROJ_LIB AFTER EXPORT"
echo $PROJ_LIB
python main.py "{'s1_ascending': '$1', 's1_descending': '$2', 'startDate':'$3', 'endDate':'$4', 'outputArtifactName': '$5', shapeArtifactName: '$6', shapeFileName: '$7'}, 'geomWKT':'$8'"
exit