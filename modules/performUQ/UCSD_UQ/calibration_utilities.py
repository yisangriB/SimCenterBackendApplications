import os  # noqa: INP001, D100
import shutil
import sys
import time
from importlib import import_module
from typing import Callable, TextIO

import numpy as np
import pdfs
from numpy.typing import NDArray
from scipy.linalg import block_diag


class DataProcessingError(Exception):
    """Raised when errors found when processing user-supplied calibration and covariance data.

    Attributes
    ----------
        message -- explanation of the error

    """

    def __init__(self, message):
        self.message = message


class CovarianceMatrixPreparer:  # noqa: D101
    def __init__(
        self,
        calibrationData: np.ndarray,  # noqa: N803
        edpLengthsList: list[int],  # noqa: FA102, N803
        edpNamesList: list[str],  # noqa: FA102, N803
        workdirMain: str,  # noqa: N803
        numExperiments: int,  # noqa: N803
        logFile: TextIO,  # noqa: N803
        runType: str,  # noqa: N803
    ) -> None:
        self.calibrationData = calibrationData
        self.edpLengthsList = edpLengthsList
        self.edpNamesList = edpNamesList
        self.workdirMain = workdirMain
        self.numExperiments = numExperiments
        self.logFile = logFile
        self.runType = runType

        self.logFile.write('\n\n==========================')
        self.logFile.write('\nProcessing options for variance/covariance:')
        self.logFile.write(
            '\n\tOne variance value or covariance matrix will be used per response quantity per experiment.'
        )
        self.logFile.write(
            '\n\tIf the user does not supply variance or covariance data, a default variance value will be\n\t'
            'used per response quantity, which is constant across experiments. The default variance is\n\t'
            'computed as the variance of the transformed data, if there is data from more than one '
            'experiment.\n\t'
            'If there is data from only one experiment, then a default variance value is computed by \n\t'
            'assuming that the standard deviation of the error is 5% of the absolute maximum value of \n\t'
            'the corresponding transformed response data.'
        )

    def getDefaultErrorVariances(self):  # noqa: N802, D102
        # For each response variable, compute the variance of the data. These will be the default error variance
        # values used in the calibration process. Values of the multiplier on these default error variance values will be
        # calibrated. There will be one such error variance value per response quantity. If there is only data from one
        # experiment,then the default error std.dev. value is assumed to be 5% of the absolute maximum value of the data
        # corresponding to that response quantity.
        defaultErrorVariances = 1e-12 * np.ones_like(  # noqa: N806
            self.edpLengthsList, dtype=float
        )
        # defaultErrorVariances = np.zeros_like(self.edpLengthsList, dtype=float)
        if (
            np.shape(self.calibrationData)[0] > 1
        ):  # if there are more than 1 rows of data, i.e. data from multiple experiments
            currentIndex = 0  # noqa: N806
            for i in range(len(self.edpLengthsList)):
                dataSlice = self.calibrationData[  # noqa: N806
                    :, currentIndex : currentIndex + self.edpLengthsList[i]
                ]
                v = np.nanvar(dataSlice)
                if v != 0:
                    defaultErrorVariances[i] = v
                currentIndex += self.edpLengthsList[i]  # noqa: N806
        else:
            currentIndex = 0  # noqa: N806
            for i in range(len(self.edpLengthsList)):
                dataSlice = self.calibrationData[  # noqa: N806
                    :, currentIndex : currentIndex + self.edpLengthsList[i]
                ]
                v = np.max(np.absolute(dataSlice))
                if v != 0:
                    defaultErrorVariances[i] = (0.05 * v) ** 2
                currentIndex += self.edpLengthsList[i]  # noqa: N806
        self.defaultErrorVariances = defaultErrorVariances

    def createCovarianceMatrix(self):  # noqa: C901, N802, D102
        covarianceMatrixList = []  # noqa: N806
        covarianceTypeList = []  # noqa: N806

        logFile = self.logFile  # noqa: N806
        edpNamesList = self.edpNamesList  # noqa: N806
        workdirMain = self.workdirMain  # noqa: N806
        numExperiments = self.numExperiments  # noqa: N806

        logFile.write('\n\nLooping over the experiments and EDPs')
        # First, check if the user has passed in any covariance matrix data
        for expNum in range(1, numExperiments + 1):  # noqa: N806
            logFile.write(f'\n\nExperiment number: {expNum}')
            for i, edpName in enumerate(edpNamesList):  # noqa: N806
                logFile.write(f'\n\tEDP: {edpName}')
                covarianceFileName = f'{edpName}.{expNum}.sigma'  # noqa: N806
                covarianceFile = os.path.join(workdirMain, covarianceFileName)  # noqa: PTH118, N806
                logFile.write(
                    f"\n\t\tChecking to see if user-supplied file '{covarianceFileName}' exists in '{workdirMain}'"
                )
                if os.path.isfile(covarianceFile):  # noqa: PTH113
                    logFile.write('\n\t\tFound a user supplied file.')
                    if self.runType == 'runningLocal':
                        src = covarianceFile
                        dst = os.path.join(workdirMain, covarianceFileName)  # noqa: PTH118
                        logFile.write(
                            f'\n\t\tCopying user-supplied covariance file from {src} to {dst}'
                        )
                        shutil.copyfile(src, dst)
                        covarianceFile = dst  # noqa: N806
                    logFile.write(
                        f"\n\t\tReading in user supplied covariance matrix from file: '{covarianceFile}'"
                    )
                    # Check the data in the covariance matrix file
                    tmpCovFile = os.path.join(  # noqa: PTH118, N806
                        workdirMain, 'quoFEMTempCovMatrixFile.sigma'
                    )
                    numRows = 0  # noqa: N806
                    numCols = 0  # noqa: N806
                    linenum = 0
                    with open(tmpCovFile, 'w') as f1:  # noqa: SIM117, PTH123
                        with open(covarianceFile) as f:  # noqa: PTH123
                            for line in f:
                                linenum += 1
                                if len(line.strip()) == 0:
                                    continue
                                else:  # noqa: RET507
                                    line = line.replace(',', ' ')  # noqa: PLW2901
                                    # Check the length of the line
                                    words = line.split()
                                    if numRows == 0:
                                        numCols = len(words)  # noqa: N806
                                    elif numCols != len(words):
                                        logFile.write(
                                            f'\nERROR: The number of columns in line {numRows} do not match the '
                                            f'number of columns in line {numRows - 1} of file {covarianceFile}.'
                                        )
                                        raise DataProcessingError(  # noqa: TRY003
                                            f'ERROR: The number of columns in line {numRows} do not match the '  # noqa: EM102
                                            f'number of columns in line {numRows - 1} of file {covarianceFile}.'
                                        )
                                    tempLine = ''  # noqa: N806
                                    for w in words:
                                        tempLine += f'{w} '  # noqa: N806
                                    # logFile.write("\ncovMatrixLine {}: ".format(linenum), tempLine)
                                    if numRows == 0:
                                        f1.write(tempLine)
                                    else:
                                        f1.write('\n')
                                        f1.write(tempLine)
                                    numRows += 1  # noqa: N806
                    covMatrix = np.genfromtxt(tmpCovFile)  # noqa: N806
                    covarianceMatrixList.append(covMatrix)
                    # os.remove(tmpCovFile)
                    logFile.write(
                        '\n\t\tFinished reading the file. Checking the dimensions of the covariance data.'
                    )
                    if numRows == 1:
                        if numCols == 1:
                            covarianceTypeList.append('scalar')
                            logFile.write(
                                '\n\t\tScalar variance value provided. The covariance matrix is an identity matrix '
                                'multiplied by this value.'
                            )
                        elif numCols == self.edpLengthsList[i]:
                            covarianceTypeList.append('diagonal')
                            logFile.write(
                                '\n\t\tA row vector provided. This will be treated as the diagonal entries of the '
                                'covariance matrix.'
                            )
                        else:
                            logFile.write(
                                f'\nERROR: The number of columns of data in the covariance matrix file {covarianceFile}'
                                f' must be either 1 or {self.edpLengthsList[i]}. Found {numCols} columns'
                            )
                            raise DataProcessingError(  # noqa: TRY003
                                f'ERROR: The number of columns of data in the covariance matrix file {covarianceFile}'  # noqa: EM102
                                f' must be either 1 or {self.edpLengthsList[i]}. Found {numCols} columns'
                            )
                    elif numRows == self.edpLengthsList[i]:
                        if numCols == 1:
                            covarianceTypeList.append('diagonal')
                            logFile.write(
                                '\t\tA column vector provided. This will be treated as the diagonal entries of the '
                                'covariance matrix.'
                            )
                        elif numCols == self.edpLengthsList[i]:
                            covarianceTypeList.append('matrix')
                            logFile.write('\n\t\tA full covariance matrix provided.')
                        else:
                            logFile.write(
                                f'\nERROR: The number of columns of data in the covariance matrix file {covarianceFile}'
                                f' must be either 1 or {self.edpLengthsList[i]}. Found {numCols} columns'
                            )
                            raise DataProcessingError(  # noqa: TRY003
                                f'ERROR: The number of columns of data in the covariance matrix file {covarianceFile}'  # noqa: EM102
                                f' must be either 1 or {self.edpLengthsList[i]}. Found {numCols} columns'
                            )
                    else:
                        logFile.write(
                            f'\nERROR: The number of rows of data in the covariance matrix file {covarianceFile}'
                            f' must be either 1 or {self.edpLengthsList[i]}. Found {numCols} rows'
                        )
                        raise DataProcessingError(  # noqa: TRY003
                            f'ERROR: The number of rows of data in the covariance matrix file {covarianceFile}'  # noqa: EM102
                            f' must be either 1 or {self.edpLengthsList[i]}. Found {numCols} rows'
                        )
                    logFile.write(f'\n\t\tCovariance matrix: {covMatrix}')
                else:
                    logFile.write(
                        '\n\t\tDid not find a user supplied file. Using the default variance value.'
                    )
                    logFile.write(
                        '\n\t\tThe covariance matrix is an identity matrix multiplied by this value.'
                    )
                    scalarVariance = np.array(self.defaultErrorVariances[i])  # noqa: N806
                    covarianceMatrixList.append(scalarVariance)
                    covarianceTypeList.append('scalar')
                    logFile.write(f'\n\t\tCovariance matrix: {scalarVariance}')
        self.covarianceMatrixList = covarianceMatrixList
        self.covarianceTypeList = covarianceTypeList
        logFile.write(
            '\n\nThe covariance matrix for prediction errors being used is:'
        )
        tmp = block_diag(*covarianceMatrixList)
        for row in tmp:
            rowString = ' '.join([f'{col:14.8g}' for col in row])  # noqa: N806
            logFile.write(f'\n\t{rowString}')
        return self.covarianceMatrixList


class CalDataPreparer:  # noqa: D101
    def __init__(
        self,
        workdirMain: str,  # noqa: N803
        workdirTemplate: str,  # noqa: N803
        calDataFileName: str,  # noqa: N803
        edpNamesList: list[str],  # noqa: FA102, N803
        edpLengthsList: list[int],  # noqa: FA102, N803
        logFile: TextIO,  # noqa: N803
    ) -> None:
        self.workdirMain = workdirMain
        self.workdirTemplate = workdirTemplate
        self.calDataFileName = calDataFileName
        self.edpNamesList = edpNamesList
        self.edpLengthsList = edpLengthsList
        self.logFile = logFile
        self.lineLength = sum(edpLengthsList)
        self.moveCalDataFile(self.calDataFileName)

    def moveCalDataFile(self, calDataFileName):  # noqa: N802, N803, D102
        os.rename(  # noqa: PTH104
            os.path.join(self.workdirTemplate, calDataFileName),  # noqa: PTH118
            os.path.join(self.workdirMain, calDataFileName),  # noqa: PTH118
        )

    def createHeadings(self):  # noqa: N802, D102
        self.logFile.write('\n\tCreating headings')
        headings = 'Exp_num interface '
        for i, edpName in enumerate(self.edpNamesList):  # noqa: N806
            if self.edpLengthsList[i] == 1:
                headings += f'{edpName} '
            else:
                for comp in range(self.edpLengthsList[i]):
                    headings += f'{edpName}_{comp + 1} '
        self.logFile.write(f'\n\t\tThe headings are: \n\t\t{headings}')
        return headings

    def createTempCalDataFile(self, calDataFile):  # noqa: N802, N803, D102
        self.tempCalDataFile = os.path.join(  # noqa: PTH118
            self.workdirMain, 'quoFEMTempCalibrationDataFile.cal'
        )
        f1 = open(self.tempCalDataFile, 'w')  # noqa: SIM115, PTH123
        headings = self.createHeadings()
        f1.write(headings)
        interface = 1
        self.numExperiments = 0
        linenum = 0
        with open(calDataFile) as f:  # noqa: PTH123
            for line in f:
                linenum += 1
                if len(line.strip()) == 0:
                    continue
                else:  # noqa: RET507
                    line = line.replace(',', ' ')  # noqa: PLW2901
                    # Check length of each line
                    words = line.split()
                    if len(words) == self.lineLength:
                        self.numExperiments += 1
                        tempLine = f'{self.numExperiments} {interface} '  # noqa: N806
                        for w in words:
                            tempLine += f'{w} '  # noqa: N806
                        self.logFile.write(
                            f'\n\tLine {linenum}, length {len(words)}: \n\t\t{tempLine}'
                        )
                        f1.write(f'\n{tempLine}')
                    else:
                        self.logFile.write(
                            f"\nERROR: The number of entries ({len(words)}) in line num {linenum} of the file '{calDataFile}' "
                            f'does not match the expected length {self.lineLength}'
                        )
                        raise DataProcessingError(  # noqa: TRY003
                            f"ERROR: The number of entries ({len(words)}) in line num {linenum} of the file '{calDataFile}' "  # noqa: EM102
                            f'does not match the expected length {self.lineLength}'
                        )
        f1.close()

    def readCleanedCalData(self):  # noqa: N802, D102
        self.calibrationData = np.atleast_2d(
            np.genfromtxt(
                self.tempCalDataFile,
                skip_header=1,
                usecols=np.arange(2, 2 + self.lineLength).tolist(),
            )
        )

    def getCalibrationData(self):  # noqa: N802, D102
        calDataFile = os.path.join(self.workdirMain, self.calDataFileName)  # noqa: PTH118, N806
        self.logFile.write(
            f'\nCalibration data file being processed: \n\t{calDataFile}\n'
        )
        self.createTempCalDataFile(calDataFile)
        self.readCleanedCalData()
        return self.calibrationData, self.numExperiments


def transform_data_function(  # noqa: D103
    data_to_transform: np.ndarray,
    list_of_data_segment_lengths: list[int],  # noqa: FA102
    list_of_scale_factors: list[float],  # noqa: FA102
    list_of_shift_factors: list[float],  # noqa: FA102
):
    currentPosition = 0  # noqa: N806
    for j in range(len(list_of_data_segment_lengths)):
        slice_of_data = data_to_transform[
            :,
            currentPosition : currentPosition + list_of_data_segment_lengths[j],
        ]
        slice_of_data = slice_of_data + list_of_shift_factors[j]
        data_to_transform[
            :,
            currentPosition : currentPosition + list_of_data_segment_lengths[j],
        ] = slice_of_data / list_of_scale_factors[j]
        currentPosition += list_of_data_segment_lengths[j]  # noqa: N806
    return data_to_transform


class DataTransformer:  # noqa: D101
    def __init__(self, transformStrategy: str, logFile: TextIO) -> None:  # noqa: N803
        self.logFile = logFile
        self.transformStrategyList = ['absMaxScaling', 'standardize']
        if transformStrategy not in self.transformStrategyList:
            string = ' or '.join(self.transformStrategyList)
            raise ValueError(f'transform strategy must be one of {string}')  # noqa: EM102, TRY003
        else:  # noqa: RET506
            self.transformStrategy = transformStrategy

        logFile.write(
            '\n\nFor numerical convenience, a transformation is applied to the calibration data \nand model '
            'prediction corresponding to each response quantity. \nThe calibration data and model prediction for '
            'each response variable will \nfirst be shifted (a scalar value will be added to the data and '
            'prediction) and \nthen scaled (the data and prediction will be divided by a positive scalar value).'
        )

    def computeScaleAndShiftFactors(  # noqa: N802, D102
        self,
        calibrationData: np.ndarray,  # noqa: N803
        edpLengthsList: list[int],  # noqa: FA102, N803
    ):
        self.calibrationData = calibrationData
        self.edpLengthsList = edpLengthsList

        shiftFactors = []  # noqa: N806
        scaleFactors = []  # noqa: N806
        currentPosition = 0  # noqa: N806
        locShift = 0.0  # noqa: N806
        if self.transformStrategy == 'absMaxScaling':
            # Compute the scale factors - absolute maximum of the data for each response variable
            self.logFile.write(
                '\n\nComputing scale and shift factors. '
                '\n\tThe shift factors are set to 0.0 by default.'
                '\n\tThe scale factors used are the absolute maximum of the data for each response variable.'
                '\n\tIf the absolute maximum of the data for any response variable is 0.0, '
                '\n\tthen the scale factor is set to 1.0, and the shift factor is set to 1.0.'
            )
            for j in range(len(self.edpLengthsList)):
                calibrationDataSlice = calibrationData[  # noqa: N806
                    :,
                    currentPosition : currentPosition + self.edpLengthsList[j],
                ]
                absMax = np.absolute(np.max(calibrationDataSlice))  # noqa: N806
                if absMax == 0:  # This is to handle the case if abs max of data = 0.
                    locShift = 1.0  # noqa: N806
                    absMax = 1.0  # noqa: N806
                shiftFactors.append(locShift)
                scaleFactors.append(absMax)
                currentPosition += self.edpLengthsList[j]  # noqa: N806
        else:
            self.logFile.write(
                '\n\nComputing scale and shift factors. '
                '\n\tThe shift factors are set to the negative of the mean value for each response variable.'
                '\n\tThe scale factors used are the standard deviation of the data for each response variable.'
                '\n\tIf the standard deviation of the data for any response variable is 0.0, '
                '\n\tthen the scale factor is set to 1.0.'
            )
            for j in range(len(self.edpLengthsList)):
                calibrationDataSlice = calibrationData[  # noqa: N806
                    :,
                    currentPosition : currentPosition + self.edpLengthsList[j],
                ]
                meanValue = np.nanmean(calibrationDataSlice)  # noqa: N806
                stdValue = np.nanstd(calibrationDataSlice)  # noqa: N806
                if stdValue == 0:  # This is to handle the case if stdev of data = 0.
                    stdValue = 1.0  # noqa: N806
                scaleFactors.append(stdValue)
                shiftFactors.append(-meanValue)
                currentPosition += self.edpLengthsList[j]  # noqa: N806

        self.scaleFactors = scaleFactors
        self.shiftFactors = shiftFactors
        return scaleFactors, shiftFactors

    def transformData(self):  # noqa: N802, D102
        return transform_data_function(
            self.calibrationData,
            self.edpLengthsList,
            self.scaleFactors,
            self.shiftFactors,
        )


def createLogFile(where: str, logfile_name: str):  # noqa: N802, D103
    logfile = open(os.path.join(where, logfile_name), 'w')  # noqa: SIM115, PTH118, PTH123
    logfile.write(
        'Starting analysis at: {}'.format(
            time.strftime('%a, %d %b %Y %H:%M:%S', time.localtime())
        )
    )
    logfile.write("\nRunning quoFEM's UCSD_UQ engine workflow")
    logfile.write('\nCWD: {}'.format(os.path.abspath('.')))  # noqa: PTH100
    return logfile


def syncLogFile(logFile: TextIO):  # noqa: N802, N803, D103
    logFile.flush()
    os.fsync(logFile.fileno())


def make_distributions(variables):  # noqa: C901, D103
    all_distributions_list = []

    for i in range(len(variables['names'])):
        if variables['distributions'][i] == 'Uniform':
            lower_limit = float(variables['Par1'][i])
            upper_limit = float(variables['Par2'][i])

            all_distributions_list.append(
                pdfs.Uniform(lower=lower_limit, upper=upper_limit)
            )

        if variables['distributions'][i] == 'Normal':
            mean = float(variables['Par1'][i])
            standard_deviation = float(variables['Par2'][i])

            all_distributions_list.append(
                pdfs.Normal(mu=mean, sig=standard_deviation)
            )

        if variables['distributions'][i] == 'Half-Normal':
            standard_deviation = float(variables['Par1'][i])

            all_distributions_list.append(pdfs.Halfnormal(sig=standard_deviation))

        if variables['distributions'][i] == 'Truncated-Normal':
            mean = float(variables['Par1'][i])
            standard_deviation = float(variables['Par2'][i])
            lower_limit = float(variables['Par3'][i])
            upper_limit = float(variables['Par4'][i])

            all_distributions_list.append(
                pdfs.TrunNormal(
                    mu=mean,
                    sig=standard_deviation,
                    a=lower_limit,
                    b=upper_limit,
                )
            )

        if variables['distributions'][i] == 'InvGamma':
            a = float(variables['Par1'][i])
            b = float(variables['Par2'][i])

            all_distributions_list.append(pdfs.InvGamma(a=a, b=b))

        if variables['distributions'][i] == 'Beta':
            alpha = float(variables['Par1'][i])
            beta = float(variables['Par2'][i])
            lower_limit = float(variables['Par3'][i])
            upper_limit = float(variables['Par4'][i])

            all_distributions_list.append(
                pdfs.BetaDist(
                    alpha=alpha,
                    beta=beta,
                    lowerbound=lower_limit,
                    upperbound=upper_limit,
                )
            )

        if variables['distributions'][i] == 'Lognormal':
            mu = float(variables['Par1'][i])
            sigma = float(variables['Par2'][i])

            all_distributions_list.append(pdfs.LogNormDist(mu=mu, sigma=sigma))

        if variables['distributions'][i] == 'Gumbel':
            alpha = float(variables['Par1'][i])
            beta = float(variables['Par2'][i])

            all_distributions_list.append(pdfs.GumbelDist(alpha=alpha, beta=beta))

        if variables['distributions'][i] == 'Weibull':
            shape = float(variables['Par1'][i])
            scale = float(variables['Par2'][i])

            all_distributions_list.append(pdfs.WeibullDist(shape=shape, scale=scale))

        if variables['distributions'][i] == 'Exponential':
            lamda = float(variables['Par1'][i])

            all_distributions_list.append(pdfs.ExponentialDist(lamda=lamda))

        if variables['distributions'][i] == 'Truncated exponential':
            lamda = float(variables['Par1'][i])
            lower_limit = float(variables['Par2'][i])
            upper_limit = float(variables['Par3'][i])

            all_distributions_list.append(
                pdfs.TruncatedExponentialDist(
                    lamda=lamda,
                    lower=lower_limit,
                    upper=upper_limit,
                )
            )

        if variables['distributions'][i] == 'Gamma':
            k = float(variables['Par1'][i])
            lamda = float(variables['Par2'][i])

            all_distributions_list.append(pdfs.GammaDist(k=k, lamda=lamda))

        if variables['distributions'][i] == 'Chisquare':
            k = float(variables['Par1'][i])

            all_distributions_list.append(pdfs.ChiSquareDist(k=k))

        if variables['distributions'][i] == 'Discrete':
            if variables['Par2'][i] is None:
                value = variables['Par1'][i]
                all_distributions_list.append(pdfs.ConstantInteger(value=value))
            else:
                values = float(variables['Par1'][i])
                weights = float(variables['Par2'][i])
                all_distributions_list.append(
                    pdfs.DiscreteDist(values=values, weights=weights)
                )

    return all_distributions_list


class LogLikelihoodHandler:  # noqa: D101
    def __init__(
        self,
        data: NDArray,
        covariance_matrix_blocks_list: list[NDArray],  # noqa: FA102
        list_of_data_segment_lengths: list[int],  # noqa: FA102
        list_of_scale_factors: list[float],  # noqa: FA102
        list_of_shift_factors: list[float],  # noqa: FA102
        workdir_main,
        full_path_to_tmcmc_code_directory: str,
        log_likelihood_file_name: str = '',
    ) -> None:
        self.data = data
        self.covariance_matrix_list = covariance_matrix_blocks_list
        self.list_of_data_segment_lengths = list_of_data_segment_lengths
        self.list_of_scale_factors = list_of_scale_factors
        self.list_of_shift_factors = list_of_shift_factors
        self.workdir_main = workdir_main
        self.full_path_to_tmcmc_code_directory = full_path_to_tmcmc_code_directory
        self.log_likelihood_file_name = log_likelihood_file_name
        sys.path.append(self.workdir_main)
        self._copy_log_likelihood_module()
        self.num_experiments = self._get_num_experiments()
        self.num_response_quantities = self._get_num_response_quantities()
        self.log_likelihood_function = self.get_log_likelihood_function()

    def _copy_log_likelihood_module(self):
        if (
            len(self.log_likelihood_file_name) == 0
        ):  # if the log-likelihood file is an empty string
            self.log_likelihood_file_name = 'defaultLogLikeScript.py'
            src = os.path.join(  # noqa: PTH118
                self.full_path_to_tmcmc_code_directory,
                self.log_likelihood_file_name,
            )
            dst = os.path.join(self.workdir_main, self.log_likelihood_file_name)  # noqa: PTH118
            try:
                shutil.copyfile(src, dst)
            except Exception:  # noqa: BLE001
                msg = f"ERROR: The log-likelihood script '{src}' cannot be copied to '{dst}'."
                raise Exception(msg)  # noqa: B904, TRY002

    def _get_num_experiments(self) -> int:
        return np.shape(self.data)[0]

    def _get_num_response_quantities(self) -> int:
        return len(self.list_of_data_segment_lengths)

    def _import_log_likelihood_module(
        self, log_likelihood_module_name: str
    ) -> Callable:
        try:
            module = import_module(log_likelihood_module_name)
        except:  # noqa: E722
            msg = f"\n\t\t\t\tERROR: The log-likelihood script '{os.path.join(self.workdir_main, self.log_likelihood_file_name)}' cannot be imported."  # noqa: PTH118
            raise ImportError(msg)  # noqa: B904
        return module  # type: ignore

    def get_log_likelihood_function(self) -> Callable:  # noqa: D102
        log_likelihood_module_name = os.path.splitext(self.log_likelihood_file_name)[  # noqa: PTH122
            0
        ]
        module = self._import_log_likelihood_module(log_likelihood_module_name)
        return module.log_likelihood

    def _transform_prediction(self, prediction: NDArray) -> NDArray:
        return transform_data_function(
            prediction,
            self.list_of_data_segment_lengths,
            self.list_of_scale_factors,
            self.list_of_shift_factors,
        )

    def _compute_residuals(self, transformed_prediction: NDArray) -> NDArray:
        return transformed_prediction - self.data

    def _make_mean(self, response_num: int) -> NDArray:
        return np.zeros(self.list_of_data_segment_lengths[response_num])

    def _make_covariance(self, response_num, cov_multiplier) -> NDArray:
        return cov_multiplier * np.atleast_2d(
            self.covariance_matrix_list[response_num]
        )

    def _make_input_for_log_likelihood_function(self, prediction) -> list:
        return [
            self._transform_prediction(prediction),
        ]

    def _loop_for_log_likelihood(
        self,
        prediction,
        list_of_covariance_multipliers,
    ):
        transformed_prediction = self._transform_prediction(prediction)
        allResiduals = self._compute_residuals(transformed_prediction)  # noqa: N806
        loglike = 0
        for i in range(self.num_experiments):
            currentPosition = 0  # noqa: N806
            for j in range(self.num_response_quantities):
                length = self.list_of_data_segment_lengths[j]
                residuals = allResiduals[
                    i, currentPosition : currentPosition + length
                ]
                currentPosition = currentPosition + length  # noqa: N806
                cov = self._make_covariance(j, list_of_covariance_multipliers[j])
                mean = self._make_mean(j)
                ll = self.log_likelihood_function(residuals, mean, cov)
                if not np.isnan(ll):
                    loglike += ll
                else:
                    loglike += -np.inf
        return loglike

    def evaluate_log_likelihood(  # noqa: D102
        self,
        prediction: NDArray,
        list_of_covariance_multipliers: list[float],  # noqa: FA102
    ) -> float:
        return self._loop_for_log_likelihood(
            prediction=prediction,
            list_of_covariance_multipliers=list_of_covariance_multipliers,
        )
