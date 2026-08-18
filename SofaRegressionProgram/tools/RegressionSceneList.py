import os
import tools.RegressionSceneData as RegressionSceneData
import tools.RegressionHelper as helper
import tools.RegressionWorker as RegressionWorker

import re

## Optional trailing options of a scene line. They describe a "case": the same scene
## run with arguments, which owns its own set of references.
CASE_OPTION = "--case"
ARGS_OPTION = "--args"
SCENE_LINE_OPTIONS = (CASE_OPTION, ARGS_OPTION)

## The case name is appended to the reference path, so it must stay a usable file name.
CASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


## This class is responsible for loading a file.regression-tests to gather the list of scene to test with all arguments
## It will provide the API to launch the tests or write refs on all scenes contained in this file
class RegressionSceneList:
    def __init__(self, file_path, filter, disable_progress_bar = False, verbose = False, nbr_jobs = 1):
        """
        /// Path to the file.regression-tests containing the list of scene to tests with all arguments
        std::string filePath;
        """
        self.file_path = file_path
        self.filter = filter
        self.file_dir = os.path.dirname(file_path)
        self.scenes_data_sets = [] # List<RegressionSceneData>
        self.nbr_errors = 0
        self.nbr_parsing_errors = 0 # number of lines of the list file that could not be used
        self.ref_dir_path = None
        self.used_ref_paths = {} # reference path -> line number, to detect two scenes sharing references
        self.disable_progress_bar = disable_progress_bar
        self.verbose = verbose
        self.legacy_mode = False
        self.nbr_jobs = nbr_jobs # number of scenes simulated at the same time


    def get_nbr_scenes(self):
        return len(self.scenes_data_sets)

    def get_nbr_errors(self):
        return self.nbr_errors

    def get_nbr_parsing_errors(self):
        return self.nbr_parsing_errors

    def log_scenes_errors(self):
        for scene in self.scenes_data_sets:
            scene.log_errors()
    
    def set_legacy_mode(self, legacy_mode):
        self.legacy_mode = legacy_mode


    def parsing_error(self, line_number, message):
        """Report a line of the list file that cannot be used, and count it.

        A malformed line only invalidates the scene it describes: it must never
        interrupt the parsing of the file, nor the whole regression run.
        """
        self.nbr_parsing_errors = self.nbr_parsing_errors + 1
        helper.writeError(f"{self.file_path}:{line_number}: {message}")


    def parse_case_options(self, values, line_number):
        """Split a scene line into its positional fields and its optional case.

        A case is described by the trailing options `--case <name>` and
        `--args <arg> [<arg>...]`. `--args` gathers every following field until the
        end of the line or the next option, so a scene argument must never be
        spelled `--case` or `--args`.

        Args:
            values (list): the whitespace separated fields of the line.
            line_number (int): line number in the list file, for error reporting.

        Returns:
            tuple: (positional fields, case name or None, list of scene arguments),
            or None if the case is invalid. In that case the error has already been
            reported.
        """
        option_indices = [i for i, value in enumerate(values) if value in SCENE_LINE_OPTIONS]
        if not option_indices:
            return values, None, []

        positional = values[:option_indices[0]]
        case_name = None
        scene_args = []
        args_option_seen = False

        index = option_indices[0]
        while index < len(values):
            option = values[index]
            index = index + 1

            if option == CASE_OPTION:
                if case_name is not None:
                    self.parsing_error(line_number, f"{CASE_OPTION} is given more than once. "
                                                    f"Skipping this scene.")
                    return None
                if index >= len(values) or values[index] in SCENE_LINE_OPTIONS:
                    self.parsing_error(line_number, f"{CASE_OPTION} requires a name. "
                                                    f"Skipping this scene.")
                    return None
                case_name = values[index]
                index = index + 1
                if CASE_NAME_PATTERN.match(case_name) is None:
                    # The name ends up in the reference file names, hence the restriction.
                    self.parsing_error(line_number, f"invalid case name '{case_name}': only letters, "
                                                    f"digits, '_', '.' and '-' are allowed. "
                                                    f"Skipping this scene.")
                    return None
            else: # ARGS_OPTION
                if args_option_seen:
                    self.parsing_error(line_number, f"{ARGS_OPTION} is given more than once. "
                                                    f"Skipping this scene.")
                    return None
                args_option_seen = True
                while index < len(values) and values[index] not in SCENE_LINE_OPTIONS:
                    scene_args.append(values[index])
                    index = index + 1
                if not scene_args:
                    self.parsing_error(line_number, f"{ARGS_OPTION} requires at least one argument. "
                                                    f"Skipping this scene.")
                    return None

        if scene_args and case_name is None:
            # Without a case name the run would write over the references of the
            # scene run without arguments, silently invalidating both.
            self.parsing_error(line_number, f"{ARGS_OPTION} requires {CASE_OPTION} <name>, which names "
                                            f"the set of references of this case. Skipping this scene.")
            return None

        if not positional:
            self.parsing_error(line_number, f"missing scene path before {values[option_indices[0]]}. "
                                            f"Skipping this scene.")
            return None

        return positional, case_name, scene_args


    def parse_scene_line(self, values, line_number):
        """Parse one scene line of the list file.

        Args:
            values (list): the whitespace separated fields of the line.
            line_number (int): line number in the list file, for error reporting.

        Returns:
            RegressionSceneData: the described scene, or None if the line is
            invalid. In that case the error has already been reported.
        """
        expected_fields = "<scene path> <steps> <epsilon> <meca_in_mapping> <dump_number_step>"
        expected_options = f"[{CASE_OPTION} <name>] [{ARGS_OPTION} <arg> ...]"

        parsed_options = self.parse_case_options(values, line_number)
        if parsed_options is None:
            return None
        values, case_name, scene_args = parsed_options

        if len(values) > 5:
            helper.writeWarning(f"{self.file_path}:{line_number}: expecting at most 5 fields "
                                f"({expected_fields} {expected_options}), got {len(values)}. "
                                f"Extra fields are ignored.")

        steps = 1000
        epsilon = 0.0001
        meca_in_mapping = False
        dump_number_step = 1

        if len(values) < 2:
            helper.writeWarning(f"{self.file_path}:{line_number}: cannot evaluate steps. "
                                f"Default value {steps} will be used instead.")
        else:
            try:
                steps = int(values[1])
            except ValueError:
                self.parsing_error(line_number, f"steps must be an integer, got '{values[1]}'. "
                                                f"Expecting: {expected_fields}. Skipping this scene.")
                return None
            if steps <= 0:
                self.parsing_error(line_number, f"steps must be strictly positive, got {steps}. "
                                                f"Skipping this scene.")
                return None

        if len(values) < 3:
            helper.writeWarning(f"{self.file_path}:{line_number}: cannot evaluate epsilon. "
                                f"Default value {epsilon} will be used instead.")
        else:
            try:
                epsilon = float(values[2])
            except ValueError:
                self.parsing_error(line_number, f"epsilon must be a number, got '{values[2]}'. "
                                                f"Expecting: {expected_fields}. Skipping this scene.")
                return None
            if epsilon < 0:
                self.parsing_error(line_number, f"epsilon must be positive, got {epsilon}. "
                                                f"Skipping this scene.")
                return None

        if len(values) < 4:
            helper.writeWarning(f"{self.file_path}:{line_number}: cannot evaluate meca_in_mapping. "
                                f"Default value {meca_in_mapping} will be used instead.")
        elif values[3] not in ('0', '1'):
            self.parsing_error(line_number, f"meca_in_mapping must be 0 or 1, got '{values[3]}'. "
                                            f"Expecting: {expected_fields}. Skipping this scene.")
            return None
        else:
            meca_in_mapping = (values[3] == '1')  # converting string to Bool always gives True

        if len(values) < 5:
            helper.writeWarning(f"{self.file_path}:{line_number}: cannot evaluate dump_number_step. "
                                f"Default value {dump_number_step} will be used instead.")
        else:
            try:
                dump_number_step = int(values[4])
            except ValueError:
                self.parsing_error(line_number, f"dump_number_step must be an integer, got '{values[4]}'. "
                                                f"Expecting: {expected_fields}. Skipping this scene.")
                return None
            # dump_number_step is used as a divider of the number of steps
            if dump_number_step <= 0:
                self.parsing_error(line_number, f"dump_number_step must be strictly positive, "
                                                f"got {dump_number_step}. Skipping this scene.")
                return None

        full_file_path = os.path.normpath(os.path.join(self.file_dir, values[0]))
        if not os.path.isfile(full_file_path):
            self.parsing_error(line_number, f"scene file does not exist: {full_file_path}. "
                                            f"Skipping this scene.")
            return None

        scene_extension = os.path.splitext(full_file_path)[1].lower()
        if scene_args and scene_extension not in RegressionSceneData.PYTHON_SCENE_EXTENSIONS:
            # Only SceneLoaderPY3 gives the arguments to the scene: on any other scene
            # they would be silently dropped, and the case would be a plain duplicate.
            self.parsing_error(line_number, f"{ARGS_OPTION} is only supported for python scenes "
                                            f"({', '.join(RegressionSceneData.PYTHON_SCENE_EXTENSIONS)}), "
                                            f"got '{scene_extension}'. Skipping this scene.")
            return None

        full_ref_file_path = os.path.normpath(os.path.join(self.ref_dir_path, values[0]))
        if case_name is not None:
            # This is what gives the case its own set of references, next to the ones
            # of the other cases of the same scene.
            full_ref_file_path = full_ref_file_path + "." + case_name

        previous_line = self.used_ref_paths.get(full_ref_file_path)
        if previous_line is not None:
            self.parsing_error(line_number, f"references {full_ref_file_path} are already used by "
                                            f"line {previous_line}. Give this case a distinct "
                                            f"{CASE_OPTION} name. Skipping this scene.")
            return None
        self.used_ref_paths[full_ref_file_path] = line_number

        return RegressionSceneData.RegressionSceneData(full_file_path, full_ref_file_path,
                                                       steps, epsilon, meca_in_mapping, dump_number_step,
                                                       self.disable_progress_bar, self.verbose,
                                                       case_name, scene_args)


    def process_file(self):
        with open(self.file_path, 'r') as the_file:
            data = the_file.readlines()
        the_file.close()
        
        count = 0
        for idx, line in enumerate(data):
            line_number = idx + 1

            if line.startswith("#"):
                continue

            values = line.split()
            if len(values) == 0:
                continue

            if count == 0:
                if ("$REGRESSION_DIR" in values[0]): # using environment variable
                    if ("REGRESSION_DIR" in os.environ):
                        self.ref_dir_path = values[0].replace("$REGRESSION_DIR", os.environ["REGRESSION_DIR"])
                    else:
                        self.parsing_error(line_number, f"the environment variable $REGRESSION_DIR is required but not set. "
                                                        f"Please set this variable to the root directory of your regression tests to proceed. "
                                                        f"No scene of this file will be processed.")
                        return
                else: # direct absolute or relative path
                    self.ref_dir_path = os.path.join(self.file_dir, values[0])
                    self.ref_dir_path = os.path.abspath(self.ref_dir_path)

                if not os.path.isdir(self.ref_dir_path):
                    self.parsing_error(line_number, f"reference directory does not exist: {self.ref_dir_path}. "
                                                    f"No scene of this file will be processed.")
                    return

                if self.verbose:
                    helper.writeLog(f'Reference directory mentioned by file \'{self.file_path}\': {self.ref_dir_path}')
                count = count + 1
                continue

            if self.filter is not None and re.search(self.filter, values[0]) is None:
                if self.verbose:
                    helper.writeLog(f'Filtered out {self.filter}: {values[0]}')
                continue

            # An invalid line is reported and skipped: the other scenes of the
            # file must still be processed.
            scene_data = self.parse_scene_line(values, line_number)
            if scene_data is None:
                continue

            #scene_data.printInfo()
            self.scenes_data_sets.append(scene_data)


    def build_task(self, id_scene, mode):
        """Return the task descriptor handed over to RegressionWorker for one scene.

        Each scene is run in its own process to guarantee a clean SOFA state
        (SOFA does not fully reset its global state between load/unload), which
        also makes it safe to run several of them at the same time.
        """
        return {
            "scene_list": self,
            "id_scene": id_scene,
            "scene_data": self.scenes_data_sets[id_scene],
            "mode": mode,
            "legacy": self.legacy_mode,
            "verbose": self.verbose,
        }


    def build_tasks(self, mode):
        """Return the task descriptors of every scene of this list."""
        return [self.build_task(i, mode) for i in range(len(self.scenes_data_sets))]


    def apply_result(self, task, result):
        """Collect the outcome reported by a worker process for one scene."""
        scene = self.scenes_data_sets[task["id_scene"]]

        if task["mode"] == "write":
            if not result.get("ok", False):
                helper.writeError(f"While writing references for {scene.describe()}: {result.get('error')}")
            return

        if not result.get("ok", False):
            # Hard failure (scene could not be loaded / worker crashed).
            self.nbr_errors = self.nbr_errors + 1
            helper.writeError(f"While trying to compare {scene.describe()}: {result.get('error')}")
            return

        # Bring the worker's outcome back so log_errors() reports it as usual.
        scene.apply_worker_result(result)
        if not result.get("result", False):
            self.nbr_errors = self.nbr_errors + 1


    def _run_tasks(self, mode, description):
        tasks = self.build_tasks(mode)
        return RegressionWorker.run_scene_tasks(
            tasks,
            nbr_jobs=self.nbr_jobs,
            on_result=self.apply_result,
            description=description,
            disable_progress_bar=self.disable_progress_bar)


    def write_references(self, id_scene, print_log = False):
        scene = self.scenes_data_sets[id_scene]
        if self.verbose:
            helper.writeLog(f'Writing reference files for {scene.describe()}.')

        task = self.build_task(id_scene, "write")
        result = RegressionWorker.run_scene_in_subprocess(
            scene, mode="write",
            disable_progress_bar=self.disable_progress_bar, verbose=self.verbose)
        self.apply_result(task, result)


    def write_all_references(self):
        return self._run_tasks("write", "Write all scenes from: " + self.file_path)


    def compare_references(self, id_scene):
        scene = self.scenes_data_sets[id_scene]
        if self.verbose:
            scene.print_info()

        task = self.build_task(id_scene, "compare")
        result = RegressionWorker.run_scene_in_subprocess(
            scene, mode="compare", legacy=self.legacy_mode,
            disable_progress_bar=self.disable_progress_bar, verbose=self.verbose)
        self.apply_result(task, result)


    def compare_all_references(self):
        return self._run_tasks("compare", "Compare all scenes from: " + self.file_path)


    def replay_references(self, id_scene):
        if (id_scene < 0 or id_scene >= len(self.scenes_data_sets)):
            helper.writeError(f'Id of the scene given for replay: {id_scene} is out of range [0, {len(self.scenes_data_sets) - 1}] from input regression list file.')
            return

        self.scenes_data_sets[id_scene].load_scene()
        self.scenes_data_sets[id_scene].add_compare_state()
        self.scenes_data_sets[id_scene].replay_references()
        
        
