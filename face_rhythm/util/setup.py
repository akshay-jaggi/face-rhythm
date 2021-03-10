import cv2
import torch
import numpy as np

import yaml
from pathlib import Path

from datetime import datetime
from dateutil.tz import tzlocal
from pynwb import NWBFile, NWBHDF5IO

from face_rhythm.util import helpers


def setup_project(project_path, sessions_path, run_name, overwrite_config, remote, trials):
    """
    Creates the project folder and data folder (if they don't exist)
    Creates the config file (if it doesn't exist or overwrite requested)
    Returns path to the config file

    Parameters
    ----------
    project_path (Path): path to the project (usually ./)
    sessions_path (Path): path to the session folders and videos
    run_name (str): name for this current run of Face Rhythm
    overwrite_config (bool): whether to overwrite the config
    remote (bool): whether running on remote
    trials (bool): whether using a trial structure for the recordings

    Returns
    -------
    config_filepath (str): path to the current config
    """
    project_path.mkdir(parents=True, exist_ok=True)
    (project_path / 'configs').mkdir(parents=True, exist_ok=True)
    (project_path / 'data').mkdir(parents=True, exist_ok=True)
    (project_path / 'viz').mkdir(parents=True, exist_ok=True)
    sessions_path.mkdir(parents=True, exist_ok=True)
    config_filepath = project_path / 'configs' / f'config_{run_name}.yaml'
    if not config_filepath.exists() or overwrite_config:
        generate_config(config_filepath, project_path, sessions_path, remote, trials)

    version_check()
    return config_filepath


def version_check():
    """
    Checks the versions of various important softwares.
    Prints those versions

    Parameters
    ----------

    Returns
    -------

    """
    ### find version of openCV
    # script currently works with v4.4.0
    (major_ver, minor_ver, subminor_ver) = (cv2.__version__).split('.')
    print(f'OpenCV version: {major_ver}.{minor_ver}.{subminor_ver}')
    # print(cv2.getBuildInformation())

    ### find version of pytorch
    print(f'Pytorch version: {torch.__version__}')


def generate_config(config_filepath, project_path, sessions_path, remote, trials):
    """
    Generates bare config file with just basic info

    Parameters
    ----------
    config_filepath (Path): path to config file
    project_path (Path): path to the project (usually ./)
    sessions_path (Path): path to the session folders and videos
    remote (bool): whether running on remote
    trials (bool): whether using a trial structure for the recordings

    Returns
    -------

    """

    basic_config = {'General': {},
                    'Video': {},
                    'Paths': {},
                    'ROI': {},
                    'Optic': {},
                    'Clean': {},
                    'CDR': {},
                    'PCA': {},
                    'CQT': {},
                    'TCA': {}}
    basic_config['Paths']['project'] = str(project_path)
    basic_config['Paths']['sessions'] = str(sessions_path)
    basic_config['Paths']['data'] = str(project_path / 'data')
    basic_config['Paths']['viz'] = str(project_path / 'viz')
    basic_config['Paths']['config'] = str(config_filepath)
    basic_config['General']['remote'] = remote
    basic_config['General']['trials'] = trials

    demo_path = project_path / 'viz' / 'demos'
    demo_path.mkdir(parents=True, exist_ok=True)
    basic_config['Video']['demos'] = str(demo_path)
    positional_path = project_path / 'viz' / 'positional'
    positional_path.mkdir(parents=True, exist_ok=True)
    basic_config['TCA']['dir_positional'] = str(positional_path)
    spectral_path = project_path / 'viz' / 'spectral'
    spectral_path.mkdir(parents=True, exist_ok=True)
    basic_config['TCA']['dir_spectral'] = str(spectral_path)

    with open(str(config_filepath), 'w') as f:
        yaml.safe_dump(basic_config, f)


def import_videos(config_filepath):
    """
    Loop over all sessions and find all videos for each session

    Parameters
    ----------
    config_filepath (Path): path to the config file

    Returns
    -------

    """

    config = helpers.load_config(config_filepath)
    paths = config['Paths']
    video = config['Video']
    general = config['General']
    general['sessions'] = []

    for path in Path(paths['video']).iterdir():
        if path.is_dir() and video['session_prefix'] in str(path.name):
            session = {'name': path.stem, 'videos': []}
            for vid in path.iterdir():
                if vid.suffix in ['.avi', '.mp4']:
                    session['videos'].append(str(vid))
                elif vid.suffix in ['.npy'] and general['trials']:
                    session['trial_inds'] = str(vid)
                    trial_inds = np.load(session['trial_inds'])
                    session['num_trials'] = trial_inds.shape[0]
                    session['trial_len'] = trial_inds.shape[1]
            general['sessions'].append(session)

    helpers.save_config(config, config_filepath)


def print_session_report(session):
    """
    Prints a simple report of all the session data

    Parameters
    ----------
    session (dict): session dictionary

    Returns
    -------

    """

    print(f'Current Session: {session["name"]}')
    print(f'number of videos: {session["num_vids"]}')
    print(f'number of frames per video (roughly): {session["frames_per_video"]}')
    print(f'number of frames in ALL videos (roughly): {session["frames_total"]}')


def get_video_data(config_filepath):
    """
    get info on the imported video(s): num of frames, video height and width, framerate

    Parameters
    ----------
    config_filepath (Path): path to the config file

    Returns
    -------

    """
    config = helpers.load_config(config_filepath)
    general = config['General']
    video = config['Video']

    for session in general['sessions']:
        session['num_vids'] = len(session['videos'])
        vid_lens = np.ones(session['num_vids'])
        for i, vid_path in enumerate(session['videos']):
            vid_reader = cv2.VideoCapture(vid_path)
            vid_lens[i] = int(vid_reader.get(cv2.CAP_PROP_FRAME_COUNT))
        session['vid_lens'] = vid_lens.tolist()
        session['frames_total'] = int(sum(session['vid_lens']))
        session['frames_per_video'] = int(session['frames_total'] / session['num_vids'])
        print_session_report(session)

        if video['print_filenames']:
            print(f'\n {np.array(session["videos"]).transpose()}')

    video['Fs'] = vid_reader.get(cv2.CAP_PROP_FPS)  ## Sampling rate (FPS). Manually change here if necessary
    print(f'Sampling rate pulled from video file metadata:   {round(video["Fs"], 3)} frames per second')

    vid_reader.set(1, 1)
    ok, frame = vid_reader.read()
    video['height'] = frame.shape[0]
    video['width'] = frame.shape[1]

    helpers.save_config(config, config_filepath)


def create_nwbs(config_filepath):
    """
    Create one nwb per session. This file will be used for all future data storage

    Parameters
    ----------
    config_filepath (Path): path to the config file

    Returns
    -------

    """

    config = helpers.load_config(config_filepath)
    general = config['General']
    paths = config['Paths']

    for session in general['sessions']:
        session['nwb'] = str(Path(paths['data']) / (session['name']+ '.nwb'))
        if not general['overwrite_nwbs'] and Path(session['nwb']).exists():
            print(f'nwb for {session["name"]} already exists, not overwriting')
            print('set config["General"]["overwrite_nwbs"]=True for otherwise')
            continue

        nwbfile = NWBFile(session_description=f'face rhythm data',
                          identifier=f'{session["name"]}',
                          session_start_time=datetime.now(tzlocal()),
                          file_create_date=datetime.now(tzlocal()))

        nwbfile.create_processing_module(name='Face Rhythm',
                                         description='all face rhythm related data')

        with NWBHDF5IO(session['nwb'], 'w') as io:
            io.write(nwbfile)

    helpers.save_config(config, config_filepath)


def prepare_videos(config_filepath):
    """
    Collects key video information and stores in the config

    Parameters
    ----------
    config_filepath (Path): path to the config file

    Returns
    -------

    """

    import_videos(config_filepath)
    get_video_data(config_filepath)
    create_nwbs(config_filepath)