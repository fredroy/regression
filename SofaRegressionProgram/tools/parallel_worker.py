import os
import sys


def _setup_sofa():
    if "SOFA_ROOT" in os.environ:
        sofapython3_path = os.environ["SOFA_ROOT"] + "/lib/python3/site-packages"
        if sofapython3_path not in sys.path:
            sys.path.insert(0, sofapython3_path)


def compare_scene_worker(args):
    """Worker function for parallel scene comparison.
    Runs in a separate process with its own SOFA instance.
    """
    (file_scene_path, file_ref_path, steps, epsilon,
     meca_in_mapping, dump_number_step, legacy_mode, verbose) = args

    _setup_sofa()
    import Sofa
    import SofaRuntime

    from tools.RegressionSceneData import RegressionSceneData

    scene_data = RegressionSceneData(file_scene_path, file_ref_path,
                                     steps, epsilon, meca_in_mapping, dump_number_step,
                                     disable_progress_bar=True, verbose=verbose)

    result = {
        'file_scene_path': file_scene_path,
        'load_error': None,
        'regression_failed': False,
        'error_by_dof': [],
        'total_error': [],
        'nbr_tested_frame': 0,
        'total_run_time': 0,
    }

    try:
        scene_data.load_scene()
    except Exception as e:
        result['load_error'] = str(e)
        return result

    if legacy_mode:
        scene_data.compare_legacy_references()
    else:
        scene_data.compare_references()

    result['regression_failed'] = scene_data.regression_failed
    result['error_by_dof'] = scene_data.error_by_dof
    result['total_error'] = scene_data.total_error
    result['nbr_tested_frame'] = scene_data.nbr_tested_frame
    result['total_run_time'] = scene_data.total_run_time

    return result


def write_scene_worker(args):
    """Worker function for parallel reference writing.
    Runs in a separate process with its own SOFA instance.
    """
    (file_scene_path, file_ref_path, steps, epsilon,
     meca_in_mapping, dump_number_step, verbose) = args

    _setup_sofa()
    import Sofa
    import SofaRuntime

    from tools.RegressionSceneData import RegressionSceneData

    scene_data = RegressionSceneData(file_scene_path, file_ref_path,
                                     steps, epsilon, meca_in_mapping, dump_number_step,
                                     disable_progress_bar=True, verbose=verbose)

    result = {
        'file_scene_path': file_scene_path,
        'load_error': None,
    }

    try:
        scene_data.load_scene()
    except Exception as e:
        result['load_error'] = str(e)
        return result

    scene_data.write_references()
    return result
