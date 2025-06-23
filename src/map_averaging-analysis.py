# -*- coding: utf-8 -*-
"""
Created on Fri Feb 28 12:04:08 2025

@author: lbergamasco
"""

import numpy as np
from osgeo import gdal
import os,gc

def v_ew_displ(path :str,list_filenames: list, clip:bool=False) -> np.float32:
    """
    Parameters
    ----------
    path : str
        path of the folder containing the files to process.
    list_filenames : list
        the list of the files to process.
    clip : bool, optional
        If it is True, the function will clip the
            images according to the ROI. The default is False.

    Returns
    -------
    v_displ_time_series: np.float32
        an array containing all the vetical displacement maps in the time series.
    ew_displ_time_series: np.float32
        an array containing all the east-west displacement maps in the time series.
    coh_time_series: np.float32
        an array containing all the coherence maps in the time series.
    asc_time_series: np.float32
        an array containing the total displacement in the time series acquired in the ascending direction
    desc_time_series: np.float32
        an array containing the total displacement in the time series acquired in the descending direction
    coh_asc_time_series: np.float32
        an array containing the coherence map time series acquired in ascending direction
    coh_desc_time_series: np.float32
        an array containing the coherence map time series acquired in descending direction
    """
    n_time = len(list_filenames)
    trentino_boundary_path = r"D:\AIxPA\Interferometria\ammprv_v.shp"
    if clip:
        ds = gdal.Open(os.path.join(path,"ROI_extent.tif"),gdal.GA_ReadOnly)
        ulx, xres, xskew, uly, yskew, yres  = ds.GetGeoTransform()
        sizeX = ds.RasterXSize * xres
        sizeY = ds.RasterYSize * yres
        lrx = ulx + sizeX
        lry = uly + sizeY
        ds = None
        window = (ulx, uly, lrx, lry)
    for i,f in enumerate(list_filenames):
        file_path = os.path.join(path,f)
        asc_file_path = os.path.join(file_path,"ascending")
        desc_file_path = os.path.join(file_path,"descending")
        filename_iw1 = [os.path.join(asc_file_path,"IW1",fi) for fi in os.listdir(os.path.join(asc_file_path,"IW1")) if ".tif" in fi][0]
        filename_iw2 = [os.path.join(asc_file_path,"IW2",fi) for fi in os.listdir(os.path.join(asc_file_path,"IW2")) if ".tif" in fi][0]
        gdal.Warp(filename_iw1[:-4]+"_m.tif",[filename_iw1,filename_iw2],format='GTiff',
                  options=['COMPRESS=DEFLATE','BIGTIFF=YES','TILED=YES'])
        gdal.Warp(filename_iw1[:-4]+"_mosaic.tif",filename_iw1[:-4]+"_m.tif",format='GTiff',
                  cutlineDSName=trentino_boundary_path,cutlineLayer='ammprv_v',cropToCutline=True,
                  options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        os.remove(filename_iw1[:-4]+"_m.tif")
        filename_iw1 = [os.path.join(desc_file_path,"IW1",fi) for fi in os.listdir(os.path.join(desc_file_path,"IW1")) if ".tif" in fi][0]
        filename_iw2 = [os.path.join(desc_file_path,"IW2",fi) for fi in os.listdir(os.path.join(desc_file_path,"IW2")) if ".tif" in fi][0]
        gdal.Warp(filename_iw1[:-4]+"_m.tif",[filename_iw1,filename_iw2],format='GTiff',
                  options=['COMPRESS=DEFLATE','BIGTIFF=YES','TILED=YES'])
        gdal.Warp(filename_iw1[:-4]+"_mosaic.tif",filename_iw1[:-4]+"_m.tif",format='GTiff',
                  cutlineDSName=trentino_boundary_path,cutlineLayer='ammprv_v',cropToCutline=True,
                  options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
        os.remove(filename_iw1[:-4]+"_m.tif")
        if clip:
            #clipping for ascending images
            filename_ascending = [fi for fi in os.listdir(asc_file_path) if ".tif" in fi][0]
            output_filename_ascending = filename_ascending[:-4]+"_clip.tif"
            gdal.Translate(os.path.join(asc_file_path,output_filename_ascending), 
                           os.path.join(asc_file_path,filename_ascending), projWin = window,
                           projWinSRS = "EPSG:25832")
            filename_ascending = output_filename_ascending
            
            #clipping for descending images
            filename_descending = [fi for fi in os.listdir(desc_file_path) if ".tif" in fi][0]
            output_filename_descending = filename_descending[:-4]+"_clip.tif"
            gdal.Translate(os.path.join(desc_file_path,output_filename_descending), 
                           os.path.join(desc_file_path,filename_descending), projWin = window,
                           projWinSRS = "EPSG:25832")
            filename_descending = output_filename_descending
        else:
            filename_ascending = [fi for fi in os.listdir(asc_file_path) if "mosaic.tif" in fi][0]
            filename_descending = [fi for fi in os.listdir(desc_file_path) if "mosaic.tif" in fi][0]
        
        #reading acending and descending images
        print(r"Reading: {}".format(os.path.join(asc_file_path,filename_ascending)))
        ds = gdal.Open(os.path.join(asc_file_path,filename_ascending),gdal.GA_ReadOnly)
        if i==0:
            v_displ_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            ew_displ_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            coh_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            asc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            desc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            coh_asc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            coh_desc_time_series = np.zeros([ds.RasterYSize,ds.RasterXSize,n_time],dtype=np.float32)
            
        asc = ds.GetRasterBand(1).ReadAsArray()
        coh_asc = ds.GetRasterBand(2).ReadAsArray()
        inc_angle_asc = ds.GetRasterBand(3).ReadAsArray()
        ds = None
        print(r"Reading: {}".format(os.path.join(desc_file_path,filename_descending)))
        ds = gdal.Open(os.path.join(desc_file_path,filename_descending),gdal.GA_ReadOnly)
        desc = ds.GetRasterBand(1).ReadAsArray()
        coh_desc = ds.GetRasterBand(2).ReadAsArray()
        inc_angle_desc = ds.GetRasterBand(3).ReadAsArray()
        ds = None
        #vertical and east-west displacement calculation
        v_asc = np.divide(asc,np.cos(inc_angle_asc*(np.pi/180)))
        ew_asc = np.divide(asc,np.sin(inc_angle_asc*(np.pi/180)))
        v_desc = np.divide(desc,np.cos(inc_angle_desc*(np.pi/180)))
        ew_desc = np.divide(desc,np.sin(inc_angle_desc*(np.pi/180)))
        v_displ_time_series[:,:,i] = np.mean(np.array([v_asc,v_desc]),axis=0)
        ew_displ_time_series[:,:,i] = (ew_asc-ew_desc)/2
        coh_time_series[:,:,i] = np.mean(np.array([coh_asc,coh_desc]),axis=0)
        asc_time_series[:,:,i] = np.copy(asc)
        desc_time_series[:,:,i] = np.copy(desc)
        coh_asc_time_series[:,:,i] = np.copy(coh_asc)
        coh_desc_time_series[:,:,i] = np.copy(coh_desc)
    return v_displ_time_series, ew_displ_time_series, coh_time_series, asc_time_series, desc_time_series, coh_asc_time_series, coh_desc_time_series

def main():
    path = r"D:\AIxPA\Interferometria\CanalSanBovo-202103-202109"
    # slope_map_path = r"D:\AIxPA\Interferometria\slope_map25832.tif"
    th = 0.3
    #get the list of folders to analyze
    list_filenames = [f for f in os.listdir(path) if os.path.isdir(os.path.join(path, f))]
    #get geotrasformation and projection
    ds = gdal.Open(os.path.join(path,"ROI_extent.tif"),gdal.GA_ReadOnly)
    geoT = ds.GetGeoTransform()
    proj = ds.GetProjection()
    ulx, xres, xskew, uly, yskew, yres  = geoT
    sizeX = ds.RasterXSize * xres
    sizeY = ds.RasterYSize * yres
    ROI_width = ds.RasterXSize
    ROI_height = ds.RasterYSize
    lrx = ulx + sizeX
    lry = uly + sizeY
    ds = None
    window = (ulx, uly, lrx, lry)
    
    #calculate the vertical and east-west displacements
    v_displ_maps, ew_displ_maps, coh_maps, asc, desc, coh_asc, coh_desc = v_ew_displ(path, list_filenames,clip=False)
    #keep only the interferometry maps with a mean coherence value higher than 0.3
    mean_coh = np.average(coh_maps,axis=(0,1))
    # keep_img_mask = mean_coh>=th
    # v_displ_maps = v_displ_maps[:,:,keep_img_mask]
    # ew_displ_maps = ew_displ_maps[:,:,keep_img_mask]
    # coh_maps = coh_maps[:,:,keep_img_mask]
    n_time = ew_displ_maps.shape[2]#int(np.sum(keep_img_mask))
    offset_ew_displ_maps = np.zeros(n_time,dtype=np.float32)
    offset_v_displ_maps = np.zeros(n_time,dtype=np.float32)
    offset_asc = np.zeros(n_time,dtype=np.float32)
    offset_desc = np.zeros(n_time,dtype=np.float32)
    for i in range(n_time):
        most_coh_points = coh_maps[:,:,i]>0.9
        offset_ew_displ_maps[i] = np.mean(ew_displ_maps[:,:,i][most_coh_points])
        offset_v_displ_maps[i] = np.mean(v_displ_maps[:,:,i][most_coh_points])
        offset_asc[i] = np.mean(asc[:,:,i][most_coh_points])
        offset_desc[i] = np.mean(desc[:,:,i][most_coh_points])
    ew_displ_maps -= offset_ew_displ_maps
    v_displ_maps -= offset_v_displ_maps
    asc -= offset_asc
    desc -= offset_desc
    keep_img_mask = np.logical_and(np.max(ew_displ_maps,axis=(0,1))<1,
                                  np.min(ew_displ_maps,axis=(0,1))>-1)#mean_coh>=th

    v_displ_maps = v_displ_maps[:,:,keep_img_mask]
    ew_displ_maps = ew_displ_maps[:,:,keep_img_mask]
    coh_maps = coh_maps[:,:,keep_img_mask]
    asc = asc[:,:,keep_img_mask]
    desc = desc[:,:,keep_img_mask]
    coh_asc = coh_asc[:,:,keep_img_mask]
    coh_desc = coh_desc[:,:,keep_img_mask]

    #compute the average over time
    avg_coh_map = np.average(coh_maps,axis=-1)
    masked_v_displ_maps = np.copy(v_displ_maps)
    masked_ew_displ_maps = np.copy(ew_displ_maps)

    cum_sum_ew_displ_map = np.sum(ew_displ_maps,axis=-1)
    masked_cum_sum_ew_displ_map = np.copy(cum_sum_ew_displ_map)
    masked_cum_sum_ew_displ_map[avg_coh_map<0.4] = np.nan
    
    cum_sum_v_displ_map = np.sum(v_displ_maps,axis=-1)
    masked_cum_sum_v_displ_map = np.copy(cum_sum_v_displ_map)
    masked_cum_sum_v_displ_map[avg_coh_map<0.4] = np.nan
    
    cum_sum_asc = np.sum(asc,axis=-1)
    cum_sum_desc = np.sum(desc,axis=-1)
    avg_coh_asc = np.average(coh_asc,axis=-1)
    avg_coh_desc = np.average(coh_desc, axis=-1)
    masked_cum_sum_asc = np.copy(cum_sum_asc)
    masked_cum_sum_asc[avg_coh_asc<0.4] = np.nan
    masked_cum_sum_desc = np.copy(cum_sum_desc)
    masked_cum_sum_desc[avg_coh_desc<0.4] = np.nan
    
    # #get the slopes for the analyzed area
    # ds_slope = gdal.Translate(slope_map_path[:-4]+"_clipped.tif", slope_map_path, 
    #                           projWin = window, projWinSRS = "EPSG:25832", width = ROI_width,
    #                           height = ROI_height, outputSRS  = "EPSG:25832")
    # slope_map = ds_slope.ReadAsArray()
    # ds_slope = None
    # negl_risk_mask = slope_map<=18
    # low_risk_mask = np.logical_and(slope_map>18,slope_map<=30)
    # low_risk_mask = np.logical_and(slope_map>30,slope_map<=43)
    # middle_risk_mask = slope_map>43
    
    # #mask negligible splope areas
    # masked_avg_v_displ_map[negl_risk_mask] = np.nan
    # masked_avg_ew_displ_map[negl_risk_mask] = np.nan
    
    #save the stacked masked vertical displacement maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'serie_temporale_scostamento_verticale.tif'), 
                                    masked_v_displ_maps.shape[1], masked_v_displ_maps.shape[0], masked_v_displ_maps.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(masked_v_displ_maps.shape[2]):
        masked_v_displ_maps[:,:,i][coh_maps[:,:,i]<0.6] = np.nan
        # masked_v_displ_maps[:,:,i][negl_risk_mask] = np.nan
        target_ds.GetRasterBand(i+1).WriteArray(masked_v_displ_maps[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the masked cumulative vertical displacement maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'somma_cumulata_scostamento_verticale.tif'), 
                                    masked_cum_sum_v_displ_map.shape[1], masked_cum_sum_v_displ_map.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_v_displ_map)
    target_ds = None
    gc.collect()
    
    #save the stacked masked east-west displacement maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'serie_temporale_scostamento_orizzontale.tif'), 
                                    masked_ew_displ_maps.shape[1], masked_ew_displ_maps.shape[0], masked_ew_displ_maps.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(masked_ew_displ_maps.shape[2]):
        masked_ew_displ_maps[:,:,i][coh_maps[:,:,i]<0.6] = np.nan
        # masked_ew_displ_maps[:,:,i][negl_risk_mask] = np.nan
        target_ds.GetRasterBand(i+1).WriteArray(masked_ew_displ_maps[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the masked cumulative east-west displacement map
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'somma_cumulata_scostamento_orizzontale.tif'), 
                                    masked_cum_sum_ew_displ_map.shape[1], masked_cum_sum_ew_displ_map.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_ew_displ_map)
    target_ds = None
    gc.collect()
    
    #save the stacked masked total displacement maps ascending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'serie_temporale_scostamento_totale_ascendente.tif'), 
                                    asc.shape[1], asc.shape[0], asc.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(asc.shape[2]):
        asc[:,:,i][coh_asc[:,:,i]<0.6] = np.nan
        target_ds.GetRasterBand(i+1).WriteArray(asc[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the masked cumulative total displacement map ascending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'somma_cumulata_scostamento_totale_ascendente.tif'), 
                                    masked_cum_sum_asc.shape[1], masked_cum_sum_asc.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_asc)
    target_ds = None
    gc.collect()
    
    #save the stacked masked total displacement maps descending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'serie_temporale_scostamento_totale_discendente.tif'), 
                                    desc.shape[1], desc.shape[0], desc.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(desc.shape[2]):
        desc[:,:,i][coh_desc[:,:,i]<0.6] = np.nan
        target_ds.GetRasterBand(i+1).WriteArray(desc[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the masked cumulative total displacement map ascending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'somma_cumulata_scostamento_totale_discendente.tif'), 
                                    masked_cum_sum_desc.shape[1], masked_cum_sum_desc.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(masked_cum_sum_desc)
    target_ds = None
    gc.collect()
    
    #save the average coherence map
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'mappa_coerenza_media.tif'), 
                                    avg_coh_map.shape[1], avg_coh_map.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(avg_coh_map)
    target_ds = None
    gc.collect()
    
    #save the stacked coherence maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'serie_temporale_mappe_coerenza.tif'), 
                                    avg_coh_map.shape[1], avg_coh_map.shape[0], coh_maps.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(coh_maps.shape[2]):
        target_ds.GetRasterBand(i+1).WriteArray(coh_maps[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the average coherence map ascending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'mappa_coerenza_media_ascendente.tif'), 
                                    avg_coh_asc.shape[1], avg_coh_asc.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(avg_coh_asc)
    target_ds = None
    gc.collect()
    
    #save the stacked coherence maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'serie_temporale_mappe_coerenza_ascendente.tif'), 
                                    coh_asc.shape[1], coh_asc.shape[0], coh_asc.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(coh_asc.shape[2]):
        target_ds.GetRasterBand(i+1).WriteArray(coh_asc[:,:,i])
    target_ds = None
    gc.collect()
    
    #save the average coherence map descending
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'mappa_coerenza_media_dscendente.tif'), 
                                    avg_coh_desc.shape[1], avg_coh_desc.shape[0], 1, gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    target_ds.GetRasterBand(1).WriteArray(avg_coh_desc)
    target_ds = None
    gc.collect()
    
    #save the stacked coherence maps
    target_ds = gdal.GetDriverByName('GTiff').Create(os.path.join(path,'serie_temporale_mappe_coerenza_discendente.tif'), 
                                    coh_desc.shape[1], coh_desc.shape[0], coh_desc.shape[2], gdal.GDT_Float32,
                                    options=['COMPRESS=DEFLATE','BIGTIFF=YES'])
    target_ds.SetGeoTransform(geoT)
    target_ds.SetProjection(proj)
    for i in range(coh_desc.shape[2]):
        target_ds.GetRasterBand(i+1).WriteArray(coh_desc[:,:,i])
    target_ds = None
    gc.collect()
    
if __name__ == '__main__':
    main()
        