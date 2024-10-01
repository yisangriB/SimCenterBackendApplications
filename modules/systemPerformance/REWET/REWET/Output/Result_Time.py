"""Created on Thu Nov 10 18:00:55 2022

@author: snaeimi
"""  # noqa: INP001, D400

import numpy as np
import pandas as pd


class Result_Time:  # noqa: D101
    def __init__():
        pass

    def convertTimeSecondToDay(self, data, column, time_shift=0):  # noqa: N802, D102
        data.loc[:, column] = data.loc[:, column] - time_shift
        data.loc[:, column] = data.loc[:, column] / 24 / 3600

    def convertTimeSecondToHour(self, data, column, time_shift=0):  # noqa: N802, D102
        data.loc[:, column] = data.loc[:, column] - time_shift
        data.loc[:, column] = data.loc[:, column] / 3600

    def averageOverDaysCrewTotalReport(self, crew_report):  # noqa: N802, D102
        time_max_seconds = crew_report.index.max()
        time_max_days = int(np.ceil(time_max_seconds / 24 / 3600))
        daily_crew_report = pd.DataFrame(
            index=[i + 1 for i in range(time_max_days)],
            columns=crew_report.columns,
        )
        for day in range(time_max_days):
            daily_crew = crew_report.loc[day * 24 * 3600 : (day + 1) * 24 * 3600]
            daily_crew_report.loc[day + 1] = daily_crew.mean()
        return daily_crew_report