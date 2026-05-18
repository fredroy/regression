import os
import tools.RegressionSceneData as RegressionSceneData
import tools.RegressionHelper as helper
from tools import ProgressBarHandler as pbh

import re

## This class is responsible for loading a file.regression-tests to gather the list of scene to test with all arguments
## It will provide the API to launch the tests or write refs on all scenes contained in this file
class RegressionSceneList:
    def __init__(self, file_path, filter, disable_progress_bar = False, verbose = False):
        """
        /// Path to the file.regression-tests containing the list of scene to tests with all arguments
        std::string filePath;
        """
        self.file_path = file_path
        self.filter = filter
        self.file_dir = os.path.dirname(file_path)
        self.scenes_data_sets = [] # List<RegressionSceneData>
        self.nbr_errors = 0
        self.ref_dir_path = None
        self.disable_progress_bar = disable_progress_bar
        self.verbose = verbose
        self.legacy_mode = False


    def get_nbr_scenes(self):
        return len(self.scenes_data_sets)
    
    def get_nbr_errors(self):
        return self.nbr_errors
    
    def log_scenes_errors(self):
        for scene in self.scenes_data_sets:
            scene.log_errors()
    
    def set_legacy_mode(self, legacy_mode):
        self.legacy_mode = legacy_mode

    def process_file(self):
        with open(self.file_path, 'r') as the_file:
            data = the_file.readlines()
        the_file.close()
        
        count = 0
        for idx, line in enumerate(data):
            if line[0] == "#":
                continue

            values = line.split()
            if len(values) == 0:
                continue

            if count == 0:
                if ("$REGRESSION_DIR" in values[0]): # using environment variable
                    if ("REGRESSION_DIR" in os.environ):
                        self.ref_dir_path = values[0].replace("$REGRESSION_DIR", os.environ["REGRESSION_DIR"])
                    else:
                        helper.writeError(f"The environment variable $REGRESSION_DIR is required in {self.file_path} but not set. Please set this variable to the root directory of your regression tests to proceed.")
                        return
                else: # direct absolute or relative path
                    self.ref_dir_path = os.path.join(self.file_dir, values[0])
                    self.ref_dir_path = os.path.abspath(self.ref_dir_path)

                if not os.path.isdir(self.ref_dir_path):
                    helper.writeError(f'Reference directory mentioned by file \'{self.file_path}\' does not exist: {self.ref_dir_path}')
                    return

                if self.verbose:
                    helper.writeLog(f'Reference directory mentioned by file \'{self.file_path}\': {self.ref_dir_path}')
                count = count + 1
                continue


            if len(values) != 5:
                helper.writeWarning(f"line read has not 5 arguments: {len(values)} -> {line}")
                continue

            if self.filter is not None and re.search(self.filter, values[0]) is None:
                if self.verbose:
                    helper.writeLog(f'Filtered out {self.filter}: {values[0]}')
                continue

            full_file_path = os.path.normpath(os.path.join(self.file_dir, values[0]))
            full_ref_file_path = os.path.normpath(os.path.join(self.ref_dir_path, values[0]))

            meca_in_mapping = False
            if values[3] == '1': # converting string to Bool always gives True
                meca_in_mapping = True

            scene_data = RegressionSceneData.RegressionSceneData(full_file_path, full_ref_file_path,
                                                                 values[1], values[2], meca_in_mapping, values[4],
                                                                 self.disable_progress_bar, self.verbose)

            #scene_data.printInfo()
            self.scenes_data_sets.append(scene_data)


    def write_references(self, id_scene, print_log = False):
        if self.verbose:
            helper.writeLog(f'Writing reference files for {self.scenes_data_sets[id_scene].file_scene_path}.')

        self.scenes_data_sets[id_scene].load_scene()
        if print_log is True:
            self.scenes_data_sets[id_scene].print_meca_objs()
            
        self.scenes_data_sets[id_scene].write_references()

    def write_all_references(self, pool=None):
        nbr_scenes = len(self.scenes_data_sets)

        if pool is not None:
            return self._write_all_references_parallel(pool)

        pbar_scenes = pbh.ProgressBarHandler(total=nbr_scenes, disable=self.disable_progress_bar)
        pbar_scenes.set_description("Write all scenes from: " + self.file_path)

        for i in range(0, nbr_scenes):
            self.write_references(i)
            pbar_scenes.update(1)

        pbar_scenes.close()

        return nbr_scenes

    def _write_all_references_parallel(self, pool):
        from tools.parallel_worker import write_scene_worker

        tasks = []
        for scene_data in self.scenes_data_sets:
            tasks.append((
                scene_data.file_scene_path,
                scene_data.file_ref_path,
                scene_data.steps,
                scene_data.epsilon,
                scene_data.meca_in_mapping,
                scene_data.dump_number_step,
                self.verbose,
            ))

        nbr_scenes = len(tasks)
        pbar_scenes = pbh.ProgressBarHandler(total=nbr_scenes, disable=self.disable_progress_bar)
        pbar_scenes.set_description("Write all scenes from: " + self.file_path)

        for result in pool.imap_unordered(write_scene_worker, tasks):
            if result['load_error'] is not None:
                helper.writeError(f"While trying to load: {result['load_error']}")
            pbar_scenes.update(1)

        pbar_scenes.close()
        return nbr_scenes


    def compare_references(self, id_scene):
        if self.verbose:
            self.scenes_data_sets[id_scene].print_info()

        try:
            self.scenes_data_sets[id_scene].load_scene()
        except Exception as e:
            self.nbr_errors = self.nbr_errors + 1
            helper.writeError(f"While trying to load: {str(e)}")
        else:
            if self.legacy_mode:
                result = self.scenes_data_sets[id_scene].compare_legacy_references()
            else:
                result = self.scenes_data_sets[id_scene].compare_references()
            
            if not result:
                self.nbr_errors = self.nbr_errors + 1
        

    def compare_all_references(self, pool=None):
        nbr_scenes = len(self.scenes_data_sets)

        if pool is not None:
            return self._compare_all_references_parallel(pool)

        pbar_scenes = pbh.ProgressBarHandler(total=nbr_scenes, disable=self.disable_progress_bar)
        pbar_scenes.set_description("Compare all scenes from: " + self.file_path)

        for i in range(0, nbr_scenes):
            self.compare_references(i)
            pbar_scenes.update(1)
        pbar_scenes.close()

        return nbr_scenes

    def _compare_all_references_parallel(self, pool):
        from tools.parallel_worker import compare_scene_worker

        tasks = []
        for scene_data in self.scenes_data_sets:
            tasks.append((
                scene_data.file_scene_path,
                scene_data.file_ref_path,
                scene_data.steps,
                scene_data.epsilon,
                scene_data.meca_in_mapping,
                scene_data.dump_number_step,
                self.legacy_mode,
                self.verbose,
            ))

        nbr_scenes = len(tasks)
        pbar_scenes = pbh.ProgressBarHandler(total=nbr_scenes, disable=self.disable_progress_bar)
        pbar_scenes.set_description("Compare all scenes from: " + self.file_path)

        for i, result in enumerate(pool.imap_unordered(compare_scene_worker, tasks)):
            if result['load_error'] is not None:
                self.nbr_errors += 1
                helper.writeError(f"While trying to load: {result['load_error']}")
            elif result['regression_failed']:
                self.nbr_errors += 1
                scene_data = self.scenes_data_sets[self._find_scene_index(result['file_scene_path'])]
                scene_data.regression_failed = True
                scene_data.error_by_dof = result['error_by_dof']
                scene_data.total_error = result['total_error']
                scene_data.nbr_tested_frame = result['nbr_tested_frame']
                scene_data.total_run_time = result['total_run_time']
            else:
                idx = self._find_scene_index(result['file_scene_path'])
                scene_data = self.scenes_data_sets[idx]
                scene_data.nbr_tested_frame = result['nbr_tested_frame']
                scene_data.total_run_time = result['total_run_time']
            pbar_scenes.update(1)

        pbar_scenes.close()
        return nbr_scenes

    def _find_scene_index(self, file_scene_path):
        for i, scene_data in enumerate(self.scenes_data_sets):
            if scene_data.file_scene_path == file_scene_path:
                return i
        return -1


    def replay_references(self, id_scene):
        if (id_scene < 0 or id_scene >= len(self.scenes_data_sets)):
            helper.writeError(f'Id of the scene given for replay: {id_scene} is out of range [0, {len(self.scenes_data_sets) - 1}] from input regression list file.')
            return

        self.scenes_data_sets[id_scene].load_scene()
        self.scenes_data_sets[id_scene].add_compare_state()
        self.scenes_data_sets[id_scene].replay_references()
        
        
