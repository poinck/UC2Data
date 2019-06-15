import xarray
import numpy
import sys
import enum
import csv
import re
import calendar

is_win = sys.platform in ['win32', 'win64']
if not is_win:
    from cfchecker import cfchecks

data_content_file = "data_content.txt"
variables_file = "variables.txt"
institutions_file = "institutions.txt"
sites_file = "sites.txt"


class UC2Data(xarray.Dataset):

    def __init__(self, path):
        self.path = path
        super().__init__()
        tmp = xarray.open_dataset(self.path, decode_cf=False)
        self.update(tmp, inplace=True)
        self.attrs = tmp.attrs

    def uc2_check(self):

        allowed_data_contents = get_allowed_data_contents()
        allowed_licences = get_allowed_licences()
        allowed_institutions, allowed_acronyms = get_allowed_institutions()
        allowed_locations, allowed_sites = get_allowed_sites()

        ###
        # Check global attributes
        ###
        result = dict()

        result["title"] = self.check_glob_attr("title", True, str)
        result["data_content"] = self.check_glob_attr("data_content", True, str,
                                                      allowed_values=allowed_data_contents)  # TODO: Redo this test when variable is checked
        result["source"] = self.check_glob_attr("source", True, str)
        result["version"] = self.check_glob_attr("version", True,
                                                 [int, numpy.int, numpy.int8, numpy.int16, numpy.int32, numpy.int64],
                                                 allowed_values=list(
                                                     range(1, 1000)))  # TODO: This is going to be checked in DMS
        result["Conventions"] = self.check_glob_attr("Conventions", True, str, allowed_values=["CF-1.7"])
        result["dependencies"] = self.check_glob_attr("dependencies", True,
                                                      str)  # TODO: This is going to be checked by DMS
        result["history"] = self.check_glob_attr("history", True, str)
        result["references"] = self.check_glob_attr("references", True, str)
        result["comment"] = self.check_glob_attr("comment", True, str)
        result["keywords"] = self.check_glob_attr("keywords", True, str)
        result["licence"] = self.check_glob_attr("licence", True, str, allowed_values=allowed_licences)
        result["creation_time"] = self.check_glob_attr("creation_time", True, str,
                                                       regex="[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} \+00")
        result["origin_time"] = self.check_glob_attr("origin_time", True, str,
                                                     regex="[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} \+00")  # TODO: Check later with time units.
        result["origin_lon"] = self.check_glob_attr("origin_lon", True, [numpy.float, numpy.float32, numpy.float64],
                                                    allowed_range=[-180, 180])
        result["origin_lat"] = self.check_glob_attr("origin_lat", True, [numpy.float, numpy.float32, numpy.float64],
                                                    allowed_range=[-90, 90])
        result["origin_x"] = self.check_glob_attr("origin_x", True, [numpy.float, numpy.float32, numpy.float64])
        result["origin_y"] = self.check_glob_attr("origin_y", True, [numpy.float, numpy.float32, numpy.float64])
        result["rotation_angle"] = self.check_glob_attr("rotation_angle", True,
                                                        [numpy.float, numpy.float32, numpy.float64],
                                                        allowed_range=[0, 360])

        # non-standard checks

        if "featureType" in self.attrs.keys():
            result["featureType"] = self.check_glob_attr("featureType", False, str,
                                                         allowed_values=["timeSeries", "timeSeriesProfile",
                                                                         "trajectory"])
            if result["featureType"].result != ResultCode.OK:
                return result
            featuretype = self.attrs["featureType"]
        else:
            featuretype = "None"

        if featuretype != "None":
            result["origin_z"] = self.check_glob_attr("origin_z", True, [numpy.float, numpy.float32, numpy.float64],
                                                      allowed_values=0)
        else:
            result["origin_z"] = self.check_glob_attr("origin_z", True, [numpy.float, numpy.float32, numpy.float64])

        result["location"] = self.check_glob_attr("location", True, str, allowed_values=allowed_locations)
        result["site"] = self.check_glob_attr("site", True, str, allowed_values=allowed_sites)
        if (result["location"].result != ResultCode.ERROR) & (result["site"].result != ResultCode.ERROR):
            if allowed_locations[allowed_sites.index(self.attrs["site"])] != self.attrs["location"]:
                result["site"] = CheckResult(ResultCode.ERROR, "site '" + self.attrs[
                    "site"] + "' does not match location '" + self.attrs["location"] + "'")
                result["location"] = CheckResult(ResultCode.ERROR, "site '" + self.attrs[
                    "site"] + "' does not match location '" + self.attrs["location"] + "'")

        result["institution"] = self.check_glob_attr("institution", True, str, allowed_values=allowed_institutions)
        result["acronym"] = self.check_glob_attr("acronym", True, str, allowed_values=allowed_acronyms)
        if (result["institution"].result != ResultCode.ERROR) & (result["acronym"].result != ResultCode.ERROR):
            if allowed_institutions.index(self.attrs["institution"]) != allowed_acronyms.index(self.attrs["acronym"]):
                result["instition"] = CheckResult(ResultCode.ERROR, "institution '" + self.attrs[
                    "insitution"] + "' does not match acronym '" + self.attrs["acronym"] + "'")
                result["acronym"] = CheckResult(ResultCode.ERROR, "institution '" + self.attrs[
                    "insitution"] + "' does not match acronym '" + self.attrs["acronym"] + "'")

        result["author"] = self.check_glob_attr("author", True, str)
        if result["author"].result != ResultCode.ERROR:
            result["author"] = check_person_field(self.attrs["author"], "author")

        result["contact_person"] = self.check_glob_attr("contact_person", True, str)
        if result["contact_person"].result != ResultCode.ERROR:
            result["contact_person"] = check_person_field(self.attrs["contact_person"], "contact_person")

        is_iop = False
        is_lto = False
        result["campaign"] = self.check_glob_attr("campaign", True, str, regex="^[A-Za-z0-9\._-]+$")
        if result["campaign"].result != ResultCode.ERROR:
            if self.attrs["campaign"][0:3] == "IOP":
                is_iop = True
                if (len(self.attrs["campaign"]) != 5) | (not int(self.attrs["campaign"][3:]) in range(1, 100)):
                    result["campaign"] = CheckResult(ResultCode.ERROR,
                                                     "Global attribute 'campaign': If IOP then string must be IOPxx")
            elif self.attrs["campaign"][0:4] in ["VALR", "VALM"]:
                is_lto = True
                if (len(self.attrs["campaign"]) != 6) | (not int(self.attrs["campaign"][4:]) in range(1, 100)):
                    result["campaign"] = CheckResult(ResultCode.ERROR,
                                                     "Global attribute 'campaign': If VALM/VALR then string must be VALMxx/VALRxx")


        ###
        # Check variables
        ###

        result["vrs"] = self.check_var("vrs", True, None, dims=())
        if result["vrs"].result != ResultCode.ERROR:
            result["vrs_long_name"] = self.check_var_attr("vrs", "long_name", True, str,
                                                          allowed_values="vertical reference system")
            result["vrs_system_name"] = self.check_var_attr("vrs", "system_name", True, str, allowed_values="DHHN2016")
            result["vrs_standard_name"] = self.check_var_attr("vrs", "standard_name", False, None, must_not_exist=True)

        allowed_range = None
        if featuretype == "None":
            time_dims = ("time")
            time_bounds_dims = ("time", "nv")
        elif featuretype in ["timeSeries", "timeSeriesProfile"]:
            time_dims = ("station", "ntime")
            time_bounds_dims = ("station", "ntime", "nv")
        elif featuretype == "trajectory":
            time_dims = ("trag", "ntime")
            time_bounds_dims = ("traj", "ntime", "nv")
        else: raise Exception("Unexpected featureType")

        if is_iop:
            allowed_range = [.01, 86400]
        elif is_lto:
            if result["origin_time"].result != ResultCode.ERROR:
                ndays = calendar.monthrange(int(self.attrs["origin_time"][0:4]), int(self.attrs["origin_time"][5:7]))[1]
                allowed_range = [.01, ndays * 24 * 60 * 60]

        result["time_var"] = self.check_var("time", True, [numpy.int16, numpy.int32, numpy.float],
                                            allowed_range=allowed_range, dims=time_dims)
        if result["time_var"].result != ResultCode.ERROR:
            result["time_long_name"] = self.check_var_attr("time", "long_name", True, str, allowed_values="time")
            result["time_standard_name"] = self.check_var_attr("time", "standard_name", True, str,
                                                               allowed_values="time")
            result["time_calendar"] = self.check_var_attr("time", "calendar", True, str,
                                                          allowed_values="proleptic_gregorian")
            result["axis"] = self.check_var_attr("time", "axis", True, str, allowed_values="T")
            result["time_units"] = self.check_var_attr("time", "units", True, str,
                                                       regex="seconds since [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2} \+00")
            if (result["origin_time"].result != ResultCode.ERROR) & (result["time_units"].result != ResultCode.ERROR):
                if self.attrs["origin_time"] != self.variables["time"].attrs["units"][14:]:
                    result["origin_time"] = CheckResult(ResultCode.ERROR,
                                                        "Global attribute 'origin_time' does not match units of variable 'time'.")
        if "time_bounds" in self.variables.keys():
            result["time_bounds_attr"] = self.check_var_attr("time", "bounds", True, str, allowed_values="time_bounds")
            if result["time_var"].result != ResultCode.ERROR:
                result["time_bounds_var"] = self.check_var("time_bounds", True, self.variables["time"].dtype, dims=time_bounds_dims)
                if not self.variables["time"][0].equals(self.variables["time_bounds"][0,:,1]):
                    result["time_bounds_var"] = CheckResult(ResultCode.ERROR, "second column of 'time_bounds' must equal data of variable 'time'")
            else:
                result["time_bounds_var"] = CheckResult(ResultCode.ERROR, "Cannot check variable 'time_bounds' because of error in variable 'time'")
        else:
            result["time_bounds_attr"] = self.check_var_attr("time", "bounds", False, None, must_not_exist=True)

        if featuretype == "None":
            z_dims = ("z")
            z_bounds_dims = ("z", "nv")
        elif featuretype == "timeSeries":
            z_dims = ("station")
            z_bounds_dims = ("station", "nv")
        elif featuretype == "timeSeriesProfile":
            z_dims = ("station", "ntime", "nz")
            z_bounds_dims = ("station", "ntime", "nz", "nv")
        elif featuretype == "trajectory":
            z_dims = ("traj", "ntime")
            z_bounds_dims = ("traj", "ntime", "nv")
        else: raise Exception("unexpected featureType.")

        result["z"] = self.check_var("z", True, [numpy.int, numpy.int8, numpy.int16, numpy.int32, numpy.float, numpy.float16, numpy.float32, numpy.float64],
                                     dims=z_dims)
        result["z_long_name"] = self.check_var_attr("z", "long_name", True, str, allowed_values="height above origin")
        result["z_axis"] = self.check_var_attr("z", "axis", True, str, allowed_values="Z")
        result["z_positive"] = self.check_var_attr("z", "positive", True, str, allowed_values="up")
        if result["origin_z"] != ResultCode.ERROR:
            result["z_standard_name"] = self.check_var_attr("z", "standard_name", self.attrs["origin_z"] == 0, str,
                                                        allowed_values="height_above_mean_sea_level",
                                                        must_not_exist=self.attrs["origin_z"] != 0)
        if "z_bounds" in self.variables.keys():
            result["z_bounds_attr"] = self.check_var_attr("z", "bounds", True, str, allowed_values="z_bounds")
            if result["z_var"].result != ResultCode.ERROR:
                result["z_bounds_var"] = self.check_var("z_bounds", True, self.variables["z"].dtype, dims=z_bounds_dims)
            else:
                result["z_bounds_var"] = CheckResult(ResultCode.ERROR, "Cannot check variable 'z_bounds' because of error in variable 'z'")
        else:
            result["z_bounds_attr"] = self.check_var_attr("z", "bounds", False, None, must_not_exist=True)

        if featuretype in ["timeSeries", "timeSeriesProfile"]:
            result["station_h"] = self.check_var("station_h", True,
                                                 [numpy.int, numpy.int8, numpy.int16, numpy.int32, numpy.float, numpy.float16, numpy.float32, numpy.float64],
                                                 dims=("station"))


        ###
        # TODO: Check geo between var and glob att
        ###

        return result

    def check_var(self, varname, must_exist, allowed_types, allowed_range=None, dims=None):
        exists = varname in self.variables.keys()
        if not exists:
            if must_exist:
                return CheckResult(ResultCode.ERROR, "Required variable '" + varname + "' not found.")
            else:
                return CheckResult(ResultCode.OK, "Variable '" + varname + "' not found.")

        if allowed_types is not None:
            if not type(allowed_types) == list:
                allowed_types = [allowed_types]
            if len(allowed_types) > 0:
                if not self.variables[varname].dtype in allowed_types:
                    return CheckResult(ResultCode.ERROR, "Variable '" + varname + "' has wrong type. Should be " +
                                       "one of the following: " + str(allowed_types))

        if allowed_range is not None:
            if (self.variables[varname].min() < allowed_range[0]) | (self.variables[varname].max() > allowed_range[1]):
                return CheckResult(ResultCode.ERROR,
                                   "Variable '" + varname + "' is outside allowed range" + str(allowed_range))

        if dims is not None:
            if type(dims) == list:
                dims = tuple(dims)
            elif type(dims) == str:
                dims = tuple([dims])
            if self.variables[varname].dims != dims:
                return CheckResult(ResultCode.ERROR, "Variable '" + varname + "' has wrong dimensions. Expected: " + str(dims))

        return CheckPassed

    def check_var_attr(self, varname, attrname, must_exist, allowed_types, allowed_values=None, regex=None,
                       must_not_exist=None):
        exists = attrname in self.variables[varname].attrs.keys()
        if not exists:
            if must_exist:
                return CheckResult(ResultCode.ERROR,
                                   "Variable '" + varname + "': Required variable attribute '" + attrname + "' not found.")
            else:
                if not must_not_exist:
                    return CheckResult(ResultCode.OK,
                                       "Variable '" + varname + "': Variable attribute '" + attrname + "' not found.")
        else:
            if must_not_exist:
                return CheckResult(ResultCode.ERROR,
                                   "Variable '" + varname + "' has attribute '" + attrname + "' defined. Not allowed.")

        if allowed_types is not None:
            if not type(allowed_types) == list:
                allowed_types = [allowed_types]
            if len(allowed_types) > 0:
                if not type(self.variables[varname].attrs[attrname]) in allowed_types:
                    return CheckResult(ResultCode.ERROR,
                                       "Variable '" + varname + "': Required variable attribute '" + attrname + "' has wrong type. Should be " +
                                       "one of the following: " + str(allowed_types))

        if allowed_values is not None:
            if not type(allowed_values) == list:
                allowed_values = [allowed_values]
            if len(allowed_values) > 0:
                if not self.variables[varname].attrs[attrname] in allowed_values:
                    if len(allowed_values) == 1:
                        return CheckResult(ResultCode.ERROR,
                                           "Variable '" + varname + "': Required variable attribute '" + attrname + "'  has wrong value. Should be " +
                                           str(allowed_values[0]))
                    else:
                        return CheckResult(ResultCode.ERROR,
                                           "Variable '" + varname + "': Required variable attribute '" + attrname + "' has wrong value")

        if regex is not None:
            if re.fullmatch(regex, self.variables[varname].attrs[attrname]) is None:
                return CheckResult(ResultCode.ERROR,
                                   "Global attribute '" + attrname + "' does not match regular expression " + regex)

        return CheckPassed

    def check_glob_attr(self, attrname, must_exist, allowed_types, allowed_values=None, regex=None, allowed_range=None):
        exists = attrname in self.attrs.keys()
        if not exists:
            if must_exist:
                return CheckResult(ResultCode.ERROR, "Required global attribute '" + attrname + "' not found.")
            else:
                return CheckResult(ResultCode.OK, "Global attribute '" + attrname + "' not found.")

        if not type(allowed_types) == list:
            allowed_types = [allowed_types]
        if len(allowed_types) > 0:
            if not type(self.attrs[attrname]) in allowed_types:
                return CheckResult(ResultCode.ERROR, "Global attribute '" + attrname + "' has wrong type. Should be " +
                                   "one of the following: " + str(allowed_types))

        if allowed_values is not None:
            if not type(allowed_values) == list:
                allowed_values = [allowed_values]
            if len(allowed_values) > 0:
                if not self.attrs[attrname] in allowed_values:
                    if len(allowed_values) == 1:
                        return CheckResult(ResultCode.ERROR,
                                           "Global attribute '" + attrname + "' has wrong value. Should be " +
                                           str(allowed_values[0]))
                    else:
                        return CheckResult(ResultCode.ERROR, "Global attribute '" + attrname + "' has wrong value")

        if regex is not None:
            if re.fullmatch(regex, self.attrs[attrname]) is None:
                return CheckResult(ResultCode.ERROR,
                                   "Global attribute '" + attrname + "' does not match regular expression " + regex)

        if allowed_range is not None:
            if (self.attrs[attrname] < allowed_range[0]) | (self.attrs[attrname] > allowed_range[1]):
                return CheckResult(ResultCode.ERROR,
                                   "Global attribute '" + attrname + "' is outside allowed range " + str(allowed_range))

        return CheckPassed


def check_person_field(string, attrname):
    s = string.split(';')
    for i in s:
        i_s = i.split(',')
        if not len(i_s) in [2, 3]:
            return CheckResult(ResultCode.ERROR,
                               "Global attribute '" + attrname + "': Perons must be given as last_name, first_name[, email]")
        if len(i_s) == 3:
            if re.fullmatch(r"[^@]+@[^@]+\.[^@]+", i_s[2]) is None:
                return CheckResult(ResultCode.ERROR, "Global attribute '" + attrname + "': " + i_s[
                    2] + " is not a valid email address.")
    return CheckPassed


class ResultCode(enum.Enum):
    OK = 1
    WARNING = 2
    ERROR = 3


class CheckResult:

    def __init__(self, result: ResultCode, message):
        self.result = result
        self.message = message

    def __str__(self):
        return self.message


def get_allowed_data_contents():
    out = []
    with open(data_content_file, encoding="utf-8") as csvfile:
        spamreader = csv.reader(csvfile, delimiter=';', quotechar='"')
        for row in spamreader:
            out.append(row[1])

    with open(variables_file, encoding="utf-8") as csvfile:
        spamreader = csv.reader(csvfile, delimiter=';', quotechar='"')
        for row in spamreader:
            out.append(row[3])

    return out


def get_allowed_institutions():
    inst = []
    acro = []
    with open(institutions_file, encoding="utf-8") as csvfile:
        spamreader = csv.reader(csvfile, delimiter=';', quotechar='"')
        for row in spamreader:
            inst.append(row[0])
            acro.append(row[1])

    return inst, acro


def get_allowed_sites():
    loc = []
    site = []
    with open(sites_file, encoding="utf-8") as csvfile:
        spamreader = csv.reader(csvfile, delimiter='\t', quotechar='"')
        for row in spamreader:
            loc.append(row[0])
            site.append(row[1])

    return loc, site


def get_allowed_licences():
    return ["[UC]2 MOSAIK Licence; see [UC]2 data policy available at www.uc2-program.org/uc2_data_policy.pdf",
            "[UC]2 3DO Licence; see [UC]2 data policy available at www.uc2-program.org/uc2_data_policy.pdf",
            "[UC]2 KliMoPrax Licence; see [UC]2 data policy available at www.uc2-program.org/uc2_data_policy.pdf",
            "[UC]2 UseUClim Licence; see [UC]2 data policy available at www.uc2-program.org/uc2_data_policy.pdf",
            "[UC]2 Restriced Licence; see [UC]2 data policy available at www.uc2-program.org/uc2_data_policy.pdf",
            "[UC]2 Research Licence; see [UC]2 data policy available at www.uc2-program.org/uc2_data_policy.pdf",
            "[UC]2 Open Licence; see [UC]2 data policy available at www.uc2-program.org/uc2_data_policy.pdf",
            ]


CheckPassed = CheckResult(ResultCode.OK, "Test passed.")
