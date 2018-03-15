"""
This module defines the "Patient" class (which holds the main
data object of the classifier), the "Volume" class (which
holds the DICOM data from a single volume), and the
"LabelMap" class (which holds label data).
Additionally, this module contains functions for loading 
and writing both DICOM (medical volumes) and NRRD (label
maps) data.

Authors:
 * Mateus Riva (mriva@ime.usp.br)
"""

import os, sys, glob
import numpy as np
from natsort import natsorted
import dicom, nrrd

class Patient:
    """Class containing information on a patient.

    Attributes
    ----------
    id : str
        Identifier of the patient (name or numeric id).
    volumes : :obj:`dict` of :obj:`Volume`
        Dictionary of patient volumes, keyed by ID.
    labelmaps : :obj:`dict` of :obj:`LabelMap`
        Dictionary of patient label maps, keyed by ID.
    """
    def __init__(self, id, volumes={}, labelmaps={}):
        self.id = id
        self.volumes = volumes
        self.labelmaps = labelmaps

        self._total_volume = None

    def add_volume(self, volume):
        """Adds a Volume object to the Patient's volume dict."""
        self.volumes[volume.id] = volume

    def add_labelmap(self, labelmap):
        """Adds a LabelMap object to the Patient's labelmap dict."""
        self.labelmaps[labelmap.id] = labelmap

    @property
    def total_volume(self):
        """Returns the total, valid volume of the patient.
        If not computed, this function will compute it.

        Returns
        -------
        total_volume : `dict`
            Dictionary containing voxel-wise, real and relative
            values for the total volume of non-zero voxels.
            See :mod:`lic_attributes.py` for more details.
        """
        if self._total_volume:
            return self._total_volume
        else:
            # TODO: multi-volume support? TODO: gaussian? update threshold of 5???
            volume = list(self.volumes.values())[0]
            # Count total of non-zero voxels
            self._total_volume = {"voxel": np.count_nonzero(volume.data[volume.data > 5])}
            self._total_volume["real"] = self._total_volume["voxel"] * np.prod(volume.header["spacings"])
            self._total_volume["relative"] = 1
            return self._total_volume

    @classmethod
    def build_from_folder(cls, folder_path, sequences=None):
        """ Factory method: Builds a patient from a given folder.
        This folder **must** contain at least one subfolder
        with a valid volume.

        Attributes
        ----------
        folder_path : str
            Path to the patient folder.
        sequences : `List`
            List of sequences to load. A value of `None` will load 
            all available sequences.

        Returns
        -------
        patient : :obj:`Patient`
            Built `Patient` object.
        """
        id = os.path.basename(folder_path) # ID is folder name

        # Initializing empty volume and labelmap dicts
        volumes, labelmaps = {}, {}

        # Iterating over subfolders and attempting to build data elements
        for dir in next(os.walk(folder_path))[1]:
            # If not a requested sequence, skip this subfolder
            if sequences is not None:
                if dir not in sequences:
                    continue

            # Attempting to load a volume from this folder; skipping on fail.
            try:
                new_volume = Volume.build_from_folder(os.path.join(folder_path, dir))
                volumes[new_volume.id] = new_volume
            except AssertionError:
                continue
            # Attempting to load a labelmap from this folder; skipping on fail.
            try:
                new_labelmap = LabelMap.build_from_folder(os.path.join(folder_path, dir))
                labelmaps[new_labelmap.id] = new_labelmap
            except AssertionError:
                continue

        # Asserting that at least a single volume was loaded
        assert volumes, "No volumes were loaded for patient in folder {}".format(folder_path)

        return cls(id, volumes, labelmaps)
        
class Volume:
    """ Class containing data on a single DICOM volume.

    Currently, three MRI sequences are supported:
     * T2 and other simple, single-contrast maps
     * Dixon, which contains four mappings (TODO);
     * Multi-echo, which contains few slices with many maps (TODO)

    Attributes
    ----------
    id : str
        Identifier of the volume (such as 'dixon').
    header : `dict`
        Dictionary containing relevant header data.
    data : `ndarray`
        Multidimensional data object containing raw radiometry.
    """
    def __init__(self, id, header, data):
        """Creates a Volume object with loaded data."""
        self.id = id
        self.header = header
        self.data = data

    @classmethod
    def build_from_folder(cls, folder_path):
        """ Factory method: Builds a volume from a given folder.
        This folder **must** contain a 'dicom' subfolder, where
        the DICOM files are stored.
        """
        id = os.path.basename(folder_path) # ID is folder name

        # Special sequence handling:
        assert id != "dixon", "Dixon sequences are not yet supported"
        assert id != "multiecho", "Multiecho sequences are not yet supported"

        # Assembling the dicom files path
        files_path = os.path.join(folder_path, "dicom")
        assert os.path.exists(files_path), "No 'dicom' subfolder in {}".format(folder_path)

        # Acquiring the list of dicom filenames, natural-sorted
        dicom_filenames = []
        for path, dirs, files in os.walk(files_path):
            for file in natsorted(files):
                if file.lower().endswith(".dcm"):
                    dicom_filenames.append(os.path.join(path, file))

        # Building the header from the first file
        dicom_reference_file = dicom.read_file(dicom_filenames[0])
        # Load dimensions based on the number of rows, columns, and slices (along the Z axis)
        dicom_dimensions = (int(dicom_reference_file.Rows), int(dicom_reference_file.Columns), len(dicom_filenames))
        # Load spacing values (in mm)
        dicom_pixel_spacings = (float(dicom_reference_file.PixelSpacing[0]), float(dicom_reference_file.PixelSpacing[1]), float(dicom_reference_file.SliceThickness))
        # Load initial position
        dicom_initial_position = (float(dicom_reference_file.ImagePositionPatient[0]),float(dicom_reference_file.ImagePositionPatient[1]),float(dicom_reference_file.ImagePositionPatient[2]))
        # Building header
        header = {"dimensions" : dicom_dimensions, "spacings": dicom_pixel_spacings, "initial_position": dicom_initial_position}

        # Assembling data as an ndarray
        data = np.zeros((header["dimensions"]), dtype=dicom_reference_file.pixel_array.dtype)
        for slice_count, dicom_filename in enumerate(dicom_filenames):
            # read the file corresponding file
            dicom_file = dicom.read_file(dicom_filename)
            # store the raw image data
            data[:, :, slice_count] = dicom_file.pixel_array

        return cls(id, header, data)

class LabelMap:
    """Class containing data on a single LabelMap.

    Attributes
    ----------
    id : str
        Identifier of the labelmap (such as 'dixon').
    header : `dict`
        Dictionary containing relevant header data.
    data : `ndarray`
        Three-dimensional data object containing the labelmap.
    """
    def __init__(self, id, header, data):
        """Creates a LabelMap object with loaded data."""
        self.id = id
        self.header = header
        self.data = data

    @classmethod
    def build_from_folder(cls, folder_path):
        """ Factory method: Builds a labelmap from a given folder.
        This folder **must** contain a 'labelmap' nrrd file.
        """
        id = os.path.basename(folder_path) # ID is folder name

        # Asserting existence of nrrd file
        assert glob.glob(os.path.join(folder_path, "*_{}_labelmap.nrrd".format(id))), "No NRRD labelmap in folder {}".format(folder_path)

        # Loading labelmap nrrd file as "*_<id>_labelmap.nrrd"
        data, header = nrrd.read(glob.glob(os.path.join(folder_path, "*_{}_labelmap.nrrd".format(id)))[0])

        # Raw NRRD data must be transposed, as it is saved in a different orientation
        data = data.transpose((1,0,2))

        return cls(id, header, data)

if __name__ == '__main__':
    """Debug main function. Delete me for release"""
    patient = Patient.build_from_folder("data/4")
    print(patient)
    print(patient.volumes)
    print(patient.labelmaps)
    print(patient.volumes['t2'].header)
    print(patient.volumes['t2'].data.shape)
    print(patient.labelmaps['t2'].header)
    print(patient.labelmaps['t2'].data.shape)

    import matplotlib.pyplot as plt
    for slice in np.rollaxis(patient.labelmaps['t2'].data, 2)[20:21]:
        plt.imshow(slice)
        plt.show()
    for slice in np.rollaxis(patient.volumes['t2'].data, 2)[20:21]:
        plt.imshow(slice, cmap='gray')
        plt.show()