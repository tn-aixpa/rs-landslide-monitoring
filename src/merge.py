#!/usr/bin/env python

try:
    from osgeo import gdal
except ImportError:
    import gdal

try:
    progress = gdal.TermProgress_nocb
except:
    progress = gdal.TermProgress


import sys
import glob
import math

__version__ = '$id$'[5:-1]
verbose = 0
quiet = 0

def copy_raster( fh_s, xoff_s, yoff_s, xsize_s, ysize_s, band_n_s,
                 fh_t, xoff_t, yoff_t, xsize_t, ysize_t, band_n_t,
                 nodata=None ):

    if nodata is not None:
        return copy_raster_nodata(
            fh_s, xoff_s, yoff_s, xsize_s, ysize_s, band_n_s,
            fh_t, xoff_t, yoff_t, xsize_t, ysize_t, band_n_t,
            nodata )

    if verbose != 0:
        print('Copy %d,%d,%d,%d to %d,%d,%d,%d.' \
              % (xoff_s, yoff_s, xsize_s, ysize_s,
             xoff_t, yoff_t, xsize_t, ysize_t ))

    band_s = fh_s.GetRasterBand( band_n_s )
    band_t = fh_t.GetRasterBand( band_n_t )

    data = band_s.ReadRaster( xoff_s, yoff_s, xsize_s, ysize_s,
                             xsize_t, ysize_t, band_t.DataType )
    band_t.WriteRaster( xoff_t, yoff_t, xsize_t, ysize_t,
                        data, xsize_t, ysize_t, band_t.DataType )


    return 0

# =============================================================================
def copy_raster_nodata( fh_s, xoff_s, yoff_s, xsize_s, ysize_s, band_n_s,
                        fh_t, xoff_t, yoff_t, xsize_t, ysize_t, band_n_t,
                        nodata ):
    try:
        import numpy as Numeric
    except ImportError:
        import Numeric

    if verbose != 0:
        print('Copy %d,%d,%d,%d to %d,%d,%d,%d.' \
              % (xoff_s, yoff_s, xsize_s, ysize_s,
             xoff_t, yoff_t, xsize_t, ysize_t ))

    s_band = fh_s.GetRasterBand( band_n_s )
    t_band = fh_t.GetRasterBand( band_n_t )

    src_data = s_band.ReadAsArray( xoff_s, yoff_s, xsize_s, ysize_s,
                                   xsize_t, ysize_t )
    dst_data = t_band.ReadAsArray( xoff_t, yoff_t, xsize_t, ysize_t )

    test_nodata = Numeric.equal(src_data,nodata)
    write = Numeric.choose( test_nodata, (src_data, dst_data) )

    t_band.WriteArray( write, xoff_t, yoff_t )

    return 0

# =============================================================================
def names_to_fileinfos( name_list ):

    file_infos = []
    for name in name_list:
        info = info_file()
        if info.init_from_filename( name ) == 1:
            file_infos.append( info )

    return file_infos

# *****************************************************************************
class info_file:

    def init_from_filename(self, filename):
        ds = gdal.Open( filename )
        if ds is None:
            return 0

        self.filename = filename
        self.bands = ds.RasterCount
        self.xsize = ds.RasterXSize
        self.ysize = ds.RasterYSize
        self.band_type = ds.GetRasterBand(1).DataType
        self.proj = ds.GetProjection()
        self.geoT = ds.GetGeoTransform()
        self.ulx = self.geoT[0]
        self.uly = self.geoT[3]
        self.lrx = self.ulx + self.geoT[1] * self.xsize
        self.lry = self.uly + self.geoT[5] * self.ysize

        color_tab = ds.GetRasterBand(1).GetRasterColorTable()
        if color_tab is not None:
            self.color_tab = color_tab.Clone()
        else:
            self.color_tab = None

        return 1

    def copy( self, fh_t, s_band = 1, t_band = 1, nodata_arg=None ):
        t_geoT = fh_t.GetGeoTransform()
        t_ulx = t_geoT[0]
        t_uly = t_geoT[3]
        t_lrx = t_geoT[0] + fh_t.RasterXSize * t_geoT[1]
        t_lry = t_geoT[3] + fh_t.RasterYSize * t_geoT[5]

        tw_ulx = max(t_ulx,self.ulx)
        tw_ulx = min(t_lrx,self.lrx)
        if t_geoT[5] < 0:
            tw_uly = min(t_uly,self.uly)
            tw_lry = max(t_lry,self.lry)
        else:
            tw_uly = max(t_uly,self.uly)
            tw_lry = min(t_lry,self.lry)

        if tw_ulx >= tw_ulx:
            return 1
        if t_geoT[5] < 0 and tw_uly <= tw_lry:
            return 1
        if t_geoT[5] > 0 and tw_uly >= tw_lry:
            return 1

        tw_xoff = int((tw_ulx - t_geoT[0]) / t_geoT[1] + 0.1)
        tw_yoff = int((tw_uly - t_geoT[3]) / t_geoT[5] + 0.1)
        tw_xsize = int((tw_ulx - t_geoT[0])/t_geoT[1] + 0.5) \
                   - tw_xoff
        tw_ysize = int((tw_lry - t_geoT[3])/t_geoT[5] + 0.5) \
                   - tw_yoff

        if tw_xsize < 1 or tw_ysize < 1:
            return 1

        sw_xoff = int((tw_ulx - self.geoT[0]) / self.geoT[1])
        sw_yoff = int((tw_uly - self.geoT[3]) / self.geoT[5])
        sw_xsize = int((tw_ulx - self.geoT[0]) \
                       / self.geoT[1] + 0.5) - sw_xoff
        sw_ysize = int((tw_lry - self.geoT[3]) \
                       / self.geoT[5] + 0.5) - sw_yoff

        if sw_xsize < 1 or sw_ysize < 1:
            return 1

        fh_s = gdal.Open( self.filename )

        return \
            copy_raster( fh_s, sw_xoff, sw_yoff, sw_xsize, sw_ysize, s_band,
                         fh_t, tw_xoff, tw_yoff, tw_xsize, tw_ysize, t_band,
                         nodata_arg )

def help():
    print('merge.py [-o out_filename] [-of out_format] [-co NAME=VALUE]*')
    print('         [-ps pixelsize_x pixelsize_y] [-tap] [-separate] [-q] [-v] [-pct]')
    print('         [-ul_lr ulx uly lrx lry] [-init "value [value...]"]')
    print('         [-n nodata_value] [-a_nodata output_nodata_value]')
    print('         [-ot datatype] [-createonly] input_files')
    print('         [--help-general]')
    print('')

def main( argv=None ):

    global verbose, quiet
    verbose = 0
    quiet = 0
    name_list = []
    format = 'GTiff'
    out_filename = 'output.tif'

    ulx = None
    patch_size_x = None
    sep = 0
    copy_color_tab = 0
    nodata = None
    a_nodata = None
    create_options = []
    pre_init = []
    band_type = None
    createonly = 0
    targetAlignedPixels = False

    gdal.AllRegister()
    if argv is None:
        argv = sys.argv
    argv = gdal.GeneralCmdLineProcessor( argv )
    if argv is None:
        sys.exit( 0 )

    i = 1
    while i < len(argv):
        arg = argv[i]

        if arg == '-o':
            i = i + 1
            out_filename = argv[i]

        elif arg == '-v':
            verbose = 1

        elif arg == '-q' or arg == '-quiet':
            quiet = 1

        elif arg == '-createonly':
            createonly = 1

        elif arg == '-separate':
            sep = 1

        elif arg == '-pct':
            copy_color_tab = 1

        elif arg == '-ot':
            i = i + 1
            band_type = gdal.GetDataTypeByName( argv[i] )
            if band_type == gdal.GDT_Unknown:
                print('Unknown GDAL data type: %s' % argv[i])
                sys.exit( 1 )

        elif arg == '-init':
            i = i + 1
            str_pre_init = argv[i].split()
            for x in str_pre_init:
                pre_init.append(float(x))

        elif arg == '-n':
            i = i + 1
            nodata = float(argv[i])

        elif arg == '-a_nodata':
            i = i + 1
            a_nodata = float(argv[i])

        elif arg == '-f':
            i = i + 1
            format = argv[i]

        elif arg == '-of':
            i = i + 1
            format = argv[i]

        elif arg == '-co':
            i = i + 1
            create_options.append( argv[i] )

        elif arg == '-ps':
            patch_size_x = float(argv[i+1])
            patch_size_y = -1 * abs(float(argv[i+2]))
            i = i + 2

        elif arg == '-tap':
            targetAlignedPixels = True

        elif arg == '-ul_lr':
            ulx = float(argv[i+1])
            uly = float(argv[i+2])
            lrx = float(argv[i+3])
            lry = float(argv[i+4])
            i = i + 4

        elif arg[:1] == '-':
            print('Unrecognised command option: %s' % arg)
            Usage()
            sys.exit( 1 )

        else:
            f = glob.glob( arg )
            if len(f) == 0:
                print('File not found: "%s"' % (str( arg )))
            name_list += f 
        i = i + 1

    if len(name_list) == 0:
        print('No input files selected.')
        Usage()
        sys.exit( 1 )

    Driver = gdal.GetDriverByName(format)
    if Driver is None:
        print('Format driver %s not found, pick a supported driver.' % format)
        sys.exit( 1 )

    DriverMD = Driver.GetMetadata()
    if 'DCAP_CREATE' not in DriverMD:
        print('Format driver %s does not support creation and piecewise writing.\nPlease select a format that does, such as GTiff (the default) or HFA (Erdas Imagine).' % format)
        sys.exit( 1 )

    # Collect information on all the source files.
    file_infos = names_to_fileinfos( name_list )

    if ulx is None:
        ulx = file_infos[0].ulx
        uly = file_infos[0].uly
        lrx = file_infos[0].lrx
        lry = file_infos[0].lry

        for infos in file_infos:
            ulx = min(ulx, infos.ulx)
            uly = max(uly, infos.uly)
            lrx = max(lrx, infos.lrx)
            lry = min(lry, infos.lry)

    if patch_size_x is None:
        patch_size_x = file_infos[0].geoT[1]
        patch_size_y = file_infos[0].geoT[5]

    if band_type is None:
        band_type = file_infos[0].band_type

    # Try opening as an existing file.
    gdal.PushErrorHandler( 'CPLQuietErrorHandler' )
    fh_t = gdal.Open( out_filename, gdal.GA_Update )
    gdal.PopErrorHandler()

    # Create output file if it does not already exist.
    if fh_t is None:

        if targetAlignedPixels:
            ulx = math.floor(ulx / patch_size_x) * patch_size_x
            lrx = math.ceil(lrx / patch_size_x) * patch_size_x
            lry = math.floor(lry / -patch_size_y) * -patch_size_y
            uly = math.ceil(uly / -patch_size_y) * -patch_size_y

        geoT = [ulx, patch_size_x, 0, uly, 0, patch_size_y]

        xsize = int((lrx - ulx) / geoT[1] + 0.5)
        ysize = int((lry - uly) / geoT[5] + 0.5)


        if sep != 0:
            bands=0

            for infos in file_infos:
                bands=bands + infos.bands
        else:
            bands = file_infos[0].bands


        fh_t = Driver.Create( out_filename, xsize, ysize, bands,
                              band_type, create_options )
        if fh_t is None:
            print('Creation failed, terminating gdal_merge.')
            sys.exit( 1 )

        fh_t.SetGeoTransform( geoT )
        fh_t.SetProjection( file_infos[0].proj )

        if copy_color_tab:
            fh_t.GetRasterBand(1).SetRasterColorTable(file_infos[0].color_tab)
    else:
        if sep != 0:
            bands=0
            for infos in file_infos:
                bands=bands + infos.bands
            if fh_t.RasterCount < bands :
                print('Existing output file has less bands than the input files. You should delete it before. Terminating gdal_merge.')
                sys.exit( 1 )
        else:
            bands = min(file_infos[0].bands,fh_t.RasterCount)

    if a_nodata is not None:
        for i in range(fh_t.RasterCount):
            fh_t.GetRasterBand(i+1).SetNoDataValue(a_nodata)

    if pre_init is not None:
        if fh_t.RasterCount <= len(pre_init):
            for i in range(fh_t.RasterCount):
                fh_t.GetRasterBand(i+1).Fill( pre_init[i] )
        elif len(pre_init) == 1:
            for i in range(fh_t.RasterCount):
                fh_t.GetRasterBand(i+1).Fill( pre_init[0] )

    # Copy data from source files into output file.
    t_band = 1

    if quiet == 0 and verbose == 0:
        progress( 0.0 )
    fi_processed = 0

    for infos in file_infos:
        if createonly != 0:
            continue

        if verbose != 0:
            print("")
            print("Processing file %5d of %5d, %6.3f%% completed." \
                  % (fi_processed+1,len(file_infos),
                     fi_processed * 100.0 / len(file_infos)) )

        if sep == 0 :
            for band in range(1, bands+1):
                infos.copy( fh_t, band, band, nodata )
        else:
            for band in range(1, infos.bands+1):
                infos.copy( fh_t, band, t_band, nodata )
                t_band = t_band+1

        fi_processed = fi_processed+1
        if quiet == 0 and verbose == 0:
            progress( fi_processed / float(len(file_infos))  )

    fh_t = None

if __name__ == '__main__':
    sys.exit(main())