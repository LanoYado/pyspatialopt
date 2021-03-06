# -*- coding: UTF-8 -*-
import copy
import pulp


def update_serviceable_demand(coverage, sd):
    """
    Updates a coverage with new values from a serviceable demand dict

    :param coverage: (dict) The coverage to update
    :param sd: (dict) The corresponding serviceable demand to use as update
    :return: (dict) The coverage with the updated serviceable demands
    """
    total_serviceable_demand = 0.0
    for demand in coverage["demand"].keys():
        coverage["demand"][demand]["serviceableDemand"] = sd["demand"][demand]["serviceableDemand"]
        total_serviceable_demand += sd["demand"][demand]["serviceableDemand"]
    coverage["totalServiceableDemand"] = total_serviceable_demand
    return coverage


def validate_coverage(coverage_dict, modes, types):
    """
    Validates a coverage. Only certain coverages work in certain models
    :param coverage_dict: (dictionary) The coverage dictionary to validate
    :param modes: (list) A list of acceptable modes
    :param types: (list) A list of acceptable types
    :return:
    """
    if "type" not in coverage_dict:
        raise KeyError("'type' not found in coverage_dict")
    if "type" not in coverage_dict["type"]:
        raise KeyError("'type' not found in coverage_dict['type']")
    if coverage_dict["type"]["type"] not in types:
        raise ValueError("Expected types: '{}' got type '{}'".format(types, coverage_dict["type"]["type"]))
    if "mode" not in coverage_dict["type"]:
        raise KeyError("'mode' not found in coverage_dict['type']")
    if coverage_dict["type"]["mode"] not in modes:
        raise ValueError("Expected modes: '{}' got mode '{}'".format(modes, coverage_dict["type"]["mode"]))


def merge_coverages(coverages):
    """

    Combines multiple coverage dictionaries to form a 'master' coverage. Generally used if siting
    multiple types of facilities. Does NOT update serviceable area for partial coverage! Need to merge & dissolve all facility layers

    :param coverages: (list of dicts) The coverage dictionaries to combine
    :return: (dict) A nested dictionary storing the coverage relationships
    """
    facility_types = []
    demand_keys = []
    coverage_type = None
    for coverage in coverages:
        # make sure all coverages are of the same type (binary, partial)
        if coverage_type is None:
            coverage_type = coverage["type"]["type"]
        validate_coverage(coverage, ["coverage"], [coverage_type])
        # make sure all coverages contain unique facility types
        for facility_type in coverage["facilities"].items():
            if facility_type not in facility_types:
                facility_types.append(facility_type)
            else:
                raise ValueError("Conflicting facility types")
        demand_keys.append(set(coverage["demand"].keys()))
    # Check to make sure all demand indicies are present in all coverages
    for keys in demand_keys:
        for keys2 in demand_keys:
            if keys != keys2:
                raise ValueError("Demand Keys Invalid")

    master_coverage = copy.deepcopy(coverages[0])
    for c in coverages[1:]:
        coverage = copy.deepcopy(c)
        for facility_type in coverage["facilities"].keys():
            if facility_type not in master_coverage["facilities"]:
                master_coverage["facilities"][facility_type] = {}
            master_coverage["facilities"][facility_type] = coverage["facilities"][facility_type]

        for demand in coverage["demand"].keys():
            for facility_type in coverage["demand"][demand]["coverage"].keys():
                if facility_type not in master_coverage["demand"][demand]["coverage"]:
                    master_coverage["demand"][demand]["coverage"][facility_type] = {}
                for fac in coverage["demand"][demand]["coverage"][facility_type].keys():
                    master_coverage["demand"][demand]["coverage"][facility_type][fac] = \
                        coverage["demand"][demand]["coverage"][facility_type][fac]
                    # Update serviceable demand for binary coverage
                    if coverage_type == "Binary" and coverage["demand"][demand]["coverage"][facility_type][fac] == 1:
                        master_coverage["demand"][demand]["serviceableDemand"] = coverage["demand"][demand]["coverage"][
                            "demand"]
    return master_coverage


def create_mclp_model(coverage_dict, num_fac, model_file=None, delineator="$", use_serviceable_demand=False):
    """

    Creates an MCLP model using the provided coverage and parameters
    Writes a .lp file which can be solved with Gurobi

    Church, Richard, and Charles R Velle. 1974. The maximal covering location problem.
    Papers in regional science 32 (1):101-118.

    :param coverage_dict: (dictionary) The coverage to use to generate the model
    :param num_fac: (dictionary) The dictionary of number of facilities to use
    :param model_file: (string) The model file to output
    :param delineator: (string) The character/symbol used to delineate facility and id
    :param use_serviceable_demand: (bool) Should we use the serviceable demand rather than demand
    :return: (Pulp problem) The problem to solve
    """
    if use_serviceable_demand:
        demand_var = "serviceableDemand"
    else:
        demand_var = "demand"
    if not isinstance(coverage_dict, dict):
        raise TypeError("coverage_dict is not a dictionary")
    if model_file and not (isinstance(model_file, str)):
        raise TypeError("model_file is not a string")
    if not isinstance(num_fac, dict):
        raise TypeError("num_fac is not a dictionary")
    if not isinstance(delineator, str):
        raise TypeError("delineator is not a string")
    validate_coverage(coverage_dict, ["coverage"], ["binary"])
    # create the variables
    demand_vars = {}
    for demand_id in coverage_dict["demand"]:
        demand_vars[demand_id] = pulp.LpVariable("Y{}{}".format(delineator, demand_id), 0, 1, pulp.LpInteger)
    facility_vars = {}
    for facility_type in coverage_dict["facilities"]:
        facility_vars[facility_type] = {}
        for facility_id in coverage_dict["facilities"][facility_type]:
            facility_vars[facility_type][facility_id] = \
                pulp.LpVariable("{}{}{}".format(facility_type, delineator, facility_id), 0, 1, pulp.LpInteger)
    # create the problem
    prob = pulp.LpProblem("MCLP", pulp.LpMaximize)
    # add objective
    prob += pulp.lpSum([coverage_dict["demand"][demand_id][demand_var] * demand_vars[demand_id] for demand_id in
                        coverage_dict["demand"]])
    # add coverage constraints
    for demand_id in coverage_dict["demand"]:
        to_sum = []
        for facility_type in coverage_dict["demand"][demand_id]["coverage"]:
            for facility_id in coverage_dict["demand"][demand_id]["coverage"][facility_type]:
                to_sum.append(facility_vars[facility_type][facility_id])
        prob += pulp.lpSum(to_sum) - demand_vars[demand_id] >= 0, "D{}".format(demand_id)
    # Number of total facilities
    to_sum = []
    for facility_type in coverage_dict["facilities"]:
        for facility_id in coverage_dict["facilities"][facility_type]:
            to_sum.append(facility_vars[facility_type][facility_id])
    prob += pulp.lpSum(to_sum) <= num_fac["total"], "NumTotalFacilities"
    # Number of other facility types
    for facility_type in coverage_dict["facilities"].keys():
        if facility_type in num_fac and facility_type != "total":
            to_sum = []
            for facility_id in coverage_dict["facilities"][facility_type]:
                to_sum.append(facility_vars[facility_type][facility_id])
            prob += pulp.lpSum(to_sum) <= num_fac[facility_type], "Num{}".format(facility_type)
    if model_file:
        prob.writeLP(model_file)
    return prob


def create_mclp_cc_model(coverage_dict, num_fac, model_file=None, delineator="$", use_serviceable_demand=False):
    """

        Creates an MCLPCC model using the provided coverage and parameters
        Writes a .lp file which can be solved with Gurobi

        Tong, Daoqin. 2012. Regional coverage maximization: a new model to account implicitly
        for complementary coverage. Geographical Analysis 44 (1):1-14.

        :param coverage_dict: (dictionary) The coverage to use to generate the model
        :param num_fac: (dictionary) The dictionary of number of facilities to use
        :param model_file: (string) The model file to output
        :param delineator: (string) The character/symbol used to delineate facility and id
        :param use_serviceable_demand: (bool) Should we use the serviceable demand rather than demand
        :return: (Pulp problem) The problem to solve
        """
    if use_serviceable_demand:
        demand_var = "serviceableDemand"
    else:
        demand_var = "demand"
    if not isinstance(coverage_dict, dict):
        raise TypeError("coverage_dict is not a dictionary")
    if model_file and not (isinstance(model_file, str)):
        raise TypeError("model_file is not a string")
    if not isinstance(num_fac, dict):
        raise TypeError("num_fac is not a dictionary")
    if not isinstance(delineator, str):
        raise TypeError("delineator is not a string")
    validate_coverage(coverage_dict, ["coverage"], ["partial"])
    # create the variables
    demand_vars = {}
    for demand_id in coverage_dict["demand"]:
        demand_vars[demand_id] = pulp.LpVariable("Y{}{}".format(delineator, demand_id), 0, None, pulp.LpContinuous)
    facility_vars = {}
    for facility_type in coverage_dict["facilities"]:
        facility_vars[facility_type] = {}
        for facility_id in coverage_dict["facilities"][facility_type]:
            facility_vars[facility_type][facility_id] = \
                pulp.LpVariable("{}{}{}".format(facility_type, delineator, facility_id), 0, 1, pulp.LpInteger)
    # create the problem
    prob = pulp.LpProblem("MCLP", pulp.LpMaximize)
    # add objective
    prob += pulp.lpSum([coverage_dict["demand"][demand_id][demand_var] * demand_vars[demand_id] for demand_id in
                        coverage_dict["demand"]])
    # add coverage constraints
    for demand_id in coverage_dict["demand"]:
        to_sum = []
        for facility_type in coverage_dict["demand"][demand_id]["coverage"]:
            for facility_id in coverage_dict["demand"][demand_id]["coverage"][facility_type]:
                to_sum.append(coverage_dict["demand"][demand_id]["coverage"][facility_type][facility_id] *
                              facility_vars[facility_type][facility_id])
        prob += pulp.lpSum(to_sum) - 1 * demand_vars[demand_id] >= 0, "D{}".format(demand_id)
        prob += demand_vars[demand_id] <= coverage_dict["demand"][demand_id][demand_var]
    # Number of total facilities
    to_sum = []
    for facility_type in coverage_dict["facilities"]:
        for facility_id in coverage_dict["facilities"][facility_type]:
            to_sum.append(facility_vars[facility_type][facility_id])
    prob += pulp.lpSum(to_sum) <= num_fac["total"], "NumTotalFacilities"
    # Number of other facility types
    for facility_type in coverage_dict["facilities"].keys():
        if facility_type in num_fac and facility_type != "total":
            to_sum = []
            for facility_id in coverage_dict["facilities"][facility_type]:
                to_sum.append(facility_vars[facility_type][facility_id])
            prob += pulp.lpSum(to_sum) <= num_fac[facility_type], "Num{}".format(facility_type)
    if model_file:
        prob.writeLP(model_file)
    return prob


def create_threshold_model(coverage_dict, psi, model_file=None, delineator="$", use_serviceable_demand=False):
    """
    Creates a threshold model using the provided coverage and parameters
    Writes a .lp file which can be solved with Gurobi

    Murray, A. T., & Tong, D. (2009). GIS and spatial analysis in the
    media. Applied geography, 29(2), 250-259.

    :param coverage_dict: (dictionary) The coverage to use to generate the model
    :param psi: (float or int) The required threshold to cover (0-100%)
    :param model_file: (string) The model file to output
    :param delineator: (string) The character/symbol used to delineate facility and ids
    :param use_serviceable_demand: (bool) Should we use the serviceable demand rather than demand
    :return: (Pulp problem) The problem to solve
    """
    if use_serviceable_demand:
        demand_var = "serviceableDemand"
    else:
        demand_var = "demand"
    validate_coverage(coverage_dict, ["coverage"], ["binary"])
    # Check parameters
    if not isinstance(coverage_dict, dict):
        raise TypeError("coverage_dict is not a dictionary")
    if not (isinstance(psi, float) or isinstance(psi, int)):
        raise TypeError("backup weight is not float or int")
    if psi > 100.0 or psi < 0.0:
        raise ValueError("psi weight must be between 100 and 0")
    if model_file and not (isinstance(model_file, str)):
        raise TypeError("model_file is not a string")
    if not isinstance(delineator, str):
        raise TypeError("delineator is not a string")

    # create the variables
    demand_vars = {}
    for demand_id in coverage_dict["demand"]:
        demand_vars[demand_id] = pulp.LpVariable("Y{}{}".format(delineator, demand_id), 0, 1, pulp.LpInteger)
    facility_vars = {}
    for facility_type in coverage_dict["facilities"]:
        facility_vars[facility_type] = {}
        for facility_id in coverage_dict["facilities"][facility_type]:
            facility_vars[facility_type][facility_id] = pulp.LpVariable(
                "{}{}{}".format(facility_type, delineator, facility_id), 0, 1, pulp.LpInteger)
    # create the problem
    prob = pulp.LpProblem("ThresholdModel", pulp.LpMinimize)
    # Create objective, minimize number of facilities
    to_sum = []
    for facility_type in coverage_dict["facilities"]:
        for facility_id in coverage_dict["facilities"][facility_type]:
            to_sum.append(facility_vars[facility_type][facility_id])
    prob += pulp.lpSum(to_sum)
    # add coverage constraints
    for demand_id in coverage_dict["demand"]:
        to_sum = []
        for facility_type in coverage_dict["demand"][demand_id]["coverage"]:
            for facility_id in coverage_dict["demand"][demand_id]["coverage"][facility_type]:
                to_sum.append(facility_vars[facility_type][facility_id])
        prob += pulp.lpSum(to_sum) - 1 * demand_vars[demand_id] >= 0, "D{}".format(demand_id)
    # threshold constraint
    sum_demand = 0
    for demand_id in coverage_dict["demand"]:
        sum_demand += coverage_dict["demand"][demand_id][demand_var]
    to_sum = []
    for demand_id in coverage_dict["demand"]:
        # divide the demand by total demand to get percentage
        scaled_demand = float(100 / sum_demand) * coverage_dict["demand"][demand_id][demand_var]
        to_sum.append(scaled_demand * demand_vars[demand_id])
    prob += pulp.lpSum(to_sum) >= psi
    if model_file:
        prob.writeLP(model_file)
    return prob


def create_cc_threshold_model(coverage_dict, psi, model_file=None, delineator="$", use_serviceable_demand=False):
    """

    Creates a complementary coverage threshold model using the provided coverage and parameters
    Writes a .lp file which can be solved with Gurobi

    Tong, D. (2012). Regional coverage maximization: a new model to account implicitly
    for complementary coverage. Geographical Analysis, 44(1), 1-14.

    :param coverage_dict: (dictionary) The coverage to use to generate the model
    :param psi: (float or int) The required threshold to cover (0-100%)
    :param model_file: (string) The model file to output
    :param delineator: (string) The character/symbol used to delineate facility and ids
    :param use_serviceable_demand: (bool) Should we use the serviceable demand rather than demand
    :return: (Pulp problem) The generated problem to solve
    """
    if use_serviceable_demand:
        demand_var = "serviceableDemand"
    else:
        demand_var = "demand"
    validate_coverage(coverage_dict, ["coverage"], ["partial"])
    # Check parameters
    if not isinstance(coverage_dict, dict):
        raise TypeError("coverage_dict is not a dictionary")
    if not (isinstance(psi, float) or isinstance(psi, int)):
        raise TypeError("backup weight is not float or int")
    if psi > 100.0 or psi < 0.0:
        raise ValueError("psi weight must be between 100 and 0")
    if model_file and not (isinstance(model_file, str)):
        raise TypeError("model_file is not a string")
    if not isinstance(delineator, str):
        raise TypeError("delineator is not a string")
    # create the variables
    demand_vars = {}
    for demand_id in coverage_dict["demand"]:
        demand_vars[demand_id] = pulp.LpVariable("Y{}{}".format(delineator, demand_id), 0, None, pulp.LpContinuous)
    facility_vars = {}
    for facility_type in coverage_dict["facilities"]:
        facility_vars[facility_type] = {}
        for facility_id in coverage_dict["facilities"][facility_type]:
            facility_vars[facility_type][facility_id] = pulp.LpVariable(
                "{}{}{}".format(facility_type, delineator, facility_id), 0, 1, pulp.LpInteger)
    # create the problem
    prob = pulp.LpProblem("ThresholdModel", pulp.LpMinimize)
    # Create objective, minimize number of facilities
    to_sum = []
    for facility_type in coverage_dict["facilities"]:
        for facility_id in coverage_dict["facilities"][facility_type]:
            to_sum.append(facility_vars[facility_type][facility_id])
    prob += pulp.lpSum(to_sum)
    # add coverage constraints
    for demand_id in coverage_dict["demand"]:
        to_sum = []
        for facility_type in coverage_dict["demand"][demand_id]["coverage"]:
            for facility_id in coverage_dict["demand"][demand_id]["coverage"][facility_type]:
                to_sum.append(coverage_dict["demand"][demand_id]["coverage"][facility_type][facility_id] *
                              facility_vars[facility_type][facility_id])
        prob += pulp.lpSum(to_sum) - 1 * demand_vars[demand_id] >= 0, "D{}".format(demand_id)
        prob += demand_vars[demand_id] <= coverage_dict["demand"][demand_id][demand_var]
    # add threshold constraint
    sum_demand = 0
    for demand_id in coverage_dict["demand"]:
        sum_demand += coverage_dict["demand"][demand_id][demand_var]
    to_sum = []
    for demand_id in coverage_dict["demand"]:
        # divide the demand by total demand to get percentage
        scaled_demand = float(100 / sum_demand)
        to_sum.append(scaled_demand * demand_vars[demand_id])
    prob += pulp.lpSum(to_sum) >= psi, "Threshold"
    if model_file:
        prob.writeLP(model_file)
    return prob


def create_backup_model(coverage_dict, num_fac, model_file=None, delineator="$", use_serviceable_demand=False):
    """
    Creates a backup coverage model using the provided coverage and parameters
    Writes a .lp file which can be solved with Gurobi

    Church, R., & Murray, A. (2009). Coverage Business Site Selection, Location
    Analysis, and GIS (pp. 209-233). Hoboken, New Jersey: Wiley.

    Hogan, Kathleen, and Charles Revelle. 1986. Concepts and Applications of Backup Coverage.
    Management Science 32 (11):1434-1444.

    :param coverage_dict: (dictionary) The coverage to use to generate the model
    :param num_fac: (dictionary) The dictionary of number of facilities to use
    :param model_file: (string) The model file to output
    :param delineator: (string) The character/symbol used to delineate facility and ids
    :param use_serviceable_demand: (bool) Should we use the serviceable demand rather than demand
    :return: (Pulp problem) The generated problem to solve
    """
    if use_serviceable_demand:
        demand_var = "serviceableDemand"
    else:
        demand_var = "demand"
    validate_coverage(coverage_dict, ["coverage"], ["binary"])
    # Check parameters
    if not isinstance(coverage_dict, dict):
        raise TypeError("coverage_dict is not a dictionary")
    if not isinstance(num_fac, dict):
        raise TypeError("num_fac is not a dictionary")
    if model_file and not (isinstance(model_file, str)):
        raise TypeError("model_file is not a string")
    if not isinstance(delineator, str):
        raise TypeError("delineator is not a string")

    # create the variables
    demand_vars = {}
    for demand_id in coverage_dict["demand"]:
        demand_vars[demand_id] = pulp.LpVariable("U{}{}".format(delineator, demand_id), 0, 1, pulp.LpInteger)
    facility_vars = {}
    for facility_type in coverage_dict["facilities"]:
        facility_vars[facility_type] = {}
        for facility_id in coverage_dict["facilities"][facility_type]:
            facility_vars[facility_type][facility_id] = pulp.LpVariable(
                "{}{}{}".format(facility_type, delineator, facility_id), 0, None, pulp.LpInteger)
    # create the problem
    prob = pulp.LpProblem("BCLP", pulp.LpMaximize)
    # add objective
    prob += pulp.lpSum([coverage_dict["demand"][demand_id][demand_var] * demand_vars[demand_id] for demand_id in
                        coverage_dict["demand"]])
    # add coverage constraints
    for demand_id in coverage_dict["demand"]:
        to_sum = []
        for facility_type in coverage_dict["demand"][demand_id]["coverage"]:
            for facility_id in coverage_dict["demand"][demand_id]["coverage"][facility_type]:
                to_sum.append(facility_vars[facility_type][facility_id])
        prob += pulp.lpSum(to_sum) - 1 * demand_vars[demand_id] >= 1, "D{}".format(demand_id)
    # Number of total facilities
    to_sum = []
    for facility_type in coverage_dict["facilities"]:
        for facility_id in coverage_dict["facilities"][facility_type]:
            to_sum.append(facility_vars[facility_type][facility_id])
    prob += pulp.lpSum(to_sum) <= num_fac["total"], "NumTotalFacilities"
    # Number of other facility types
    for facility_type in coverage_dict["facilities"].keys():
        if facility_type in num_fac and facility_type != "total":
            to_sum = []
            for facility_id in coverage_dict["facilities"][facility_type]:
                to_sum.append(facility_vars[facility_type][facility_id])
            prob += pulp.lpSum(to_sum) <= num_fac[facility_type], "Num{}".format(facility_type)
    if model_file:
        prob.writeLP(model_file)
    return prob


def create_lscp_model(coverage_dict, model_file=None, delineator="$", ):
    """
    Creates a LSCP (Location set covering problem) using the provided coverage and
    parameters. Writes a .lp file which can be solved with Gurobi

    Church, R., & Murray, A. (2009). Coverage Business Site Selection, Location
    Analysis, and GIS (pp. 209-233). Hoboken, New Jersey: Wiley.

    :param coverage_dict: (dictionary) The coverage to use to generate the model
    :param model_file: (string) The model file to output
    :param delineator: (string) The character(s) to use to delineate the layer from the ids
    :return: (Pulp problem) The generated problem to solve
    """
    validate_coverage(coverage_dict, ["coverage"], ["binary"])
    if not isinstance(coverage_dict, dict):
        raise TypeError("coverage_dict is not a dictionary")
    if model_file and not (isinstance(model_file, str)):
        raise TypeError("model_file is not a string")
    if not isinstance(delineator, str):
        raise TypeError("delineator is not a string")
        # create the variables
    demand_vars = {}
    for demand_id in coverage_dict["demand"]:
        demand_vars[demand_id] = pulp.LpVariable("Y{}{}".format(delineator, demand_id), 0, 1, pulp.LpInteger)
    facility_vars = {}
    for facility_type in coverage_dict["facilities"]:
        facility_vars[facility_type] = {}
        for facility_id in coverage_dict["facilities"][facility_type]:
            facility_vars[facility_type][facility_id] = pulp.LpVariable(
                "{}{}{}".format(facility_type, delineator, facility_id), 0, 1, pulp.LpInteger)
    # create the problem
    prob = pulp.LpProblem("LSCP", pulp.LpMinimize)
    # Create objective, minimize number of facilities
    to_sum = []
    for facility_type in coverage_dict["facilities"]:
        for facility_id in coverage_dict["facilities"][facility_type]:
            to_sum.append(facility_vars[facility_type][facility_id])
    prob += pulp.lpSum(to_sum)
    # add coverage constraints
    for demand_id in coverage_dict["demand"]:
        to_sum = []
        for facility_type in coverage_dict["demand"][demand_id]["coverage"]:
            for facility_id in coverage_dict["demand"][demand_id]["coverage"][facility_type]:
                to_sum.append(facility_vars[facility_type][facility_id])
        # Hack to get model to "solve" when infeasible with GLPK.
        # Pulp will automatically add dummy variables when the sum is empty, since these are all the same name,
        # it seems that GLPK doesn't read the lp problem properly and fails
        if not to_sum:
            to_sum = [pulp.LpVariable("__dummy{}{}".format(delineator, demand_id), 0, 0, pulp.LpInteger)]
        prob += pulp.lpSum(to_sum) >= 1, "D{}".format(demand_id)
    if model_file:
        prob.writeLP(model_file)
    return prob


def create_traumah_model(coverage_dict, num_ad, num_tc, model_file=None, delineator="$"):
    """
    Creates a TRAUMAH (Trauma center and air depot location model) using the provided coverage and
    parameters. Writes a .lp file which can be solved with Gurobi

    Branas, C. C., MacKenzie, E. J., & ReVelle, C. S. (2000).
    A trauma resource allocation model for ambulances and hospitals. Health Services Research, 35(2), 489.

    :param coverage_dict: (dictionary) The coverage used to generate the model
    :param num_ad: (integer) The number air depots to use
    :param num_tc: (integer) The number of trauma centers to use
    :param model_file: (string) The path of the model file to output
    :param delineator: (string) The character(s) to use to delineate the layer from the ids
    :return: (Pulp problem) The generated problem to solve
    """
    demand_var = "demand"
    if not isinstance(coverage_dict, dict):
        raise TypeError("coverage_dict is not a dictionary")
    if model_file and not (isinstance(model_file, str)):
        raise TypeError("model_file is not a string")
    if not isinstance(num_ad, int):
        raise TypeError("num_ad is not an integer")
    if not isinstance(num_tc, int):
        raise TypeError("num_tc is not an integer")
    if not isinstance(delineator, str):
        raise TypeError("delineator is not a string")
    validate_coverage(coverage_dict, ["coverage"], ["traumah"])
    # create the variables
    demand_vars = {}
    ground_vars = {}
    air_vars = {}
    adtc_vars = {}
    for demand_id in coverage_dict["demand"]:
        demand_vars[demand_id] = pulp.LpVariable("Y{}{}".format(delineator, demand_id), 0, 1, pulp.LpInteger)
        ground_vars[demand_id] = pulp.LpVariable("V{}{}".format(delineator, demand_id), 0, 1, pulp.LpInteger)
        air_vars[demand_id] = pulp.LpVariable("U{}{}".format(delineator, demand_id), 0, 1, pulp.LpInteger)
    facility_vars = {}
    # create the AirDepot and TraumaCenter variables
    for facility_type in coverage_dict["facilities"]:
        facility_vars[facility_type] = {}
        for facility_id in coverage_dict["facilities"][facility_type]:
            facility_vars[facility_type][facility_id] = \
                pulp.LpVariable("{}{}{}".format(facility_type, delineator, facility_id), 0, 1, pulp.LpInteger)
    # create the AD/TC veriables (zjk)
    for ad_id in coverage_dict["facilities"]["AirDepot"]:
        for tc_id in coverage_dict["facilities"]["TraumaCenter"]:
            adtc_vars["Z{}{}{}{}".format(delineator,ad_id,delineator,tc_id)] = \
                pulp.LpVariable("Z{}{}{}{}".format(delineator, ad_id,delineator, tc_id), 0, 1, pulp.LpInteger)
    # create the problem
    prob = pulp.LpProblem("TRAUMAH", pulp.LpMaximize)
    # add objective
    prob += pulp.lpSum([coverage_dict["demand"][demand_id][demand_var] * demand_vars[demand_id] for demand_id in
                        coverage_dict["demand"]])
    # Number of air depots
    num_ad_sum = []
    for facility_id in coverage_dict["facilities"]["AirDepot"]:
        num_ad_sum.append(facility_vars["AirDepot"][facility_id])
    prob += pulp.lpSum(num_ad_sum) == num_ad, "Num{}".format("AirDepot")
    # Number of trauma centers
    num_tc_sum = []
    for facility_id in coverage_dict["facilities"]["TraumaCenter"]:
        num_tc_sum.append(facility_vars["TraumaCenter"][facility_id])
    prob += pulp.lpSum(num_tc_sum) == num_tc, "Num{}".format("TraumaCenter")

    # add ground air logical conditions
    for demand_id in coverage_dict["demand"]:
        prob += demand_vars[demand_id] - ground_vars[demand_id] - air_vars[demand_id] <= 0, "AIR_GROUND_{}".format(demand_id)

    # add ground constraints
    for demand_id in coverage_dict["demand"]:
        to_sum = []
        for tc in coverage_dict["demand"][demand_id]["coverage"]["TraumaCenter"]:
            to_sum.append(facility_vars["TraumaCenter"][tc["TraumaCenter"]])
        prob += ground_vars[demand_id] - pulp.lpSum(to_sum) <= 0, "GND_{}".format(demand_id)

    # add air constraints
    for demand_id in coverage_dict["demand"]:
        to_sum = []
        for adtc_pair in coverage_dict["demand"][demand_id]["coverage"]["ADTCPair"]:
            ad_id = adtc_pair["AirDepot"]
            tc_id = adtc_pair["TraumaCenter"]
            to_sum.append(adtc_vars["Z{}{}{}{}".format(delineator,ad_id,delineator,tc_id)])
        prob += air_vars[demand_id] - pulp.lpSum(to_sum) <= 0, "AIR_{}".format(demand_id)


    # add ground and air logical constraints
    for adtc_id in adtc_vars.keys():
        # ground constraints
        prob += adtc_vars[adtc_id] - facility_vars["TraumaCenter"][adtc_id.split("$")[2]] <= 0, "GND_{}".format(adtc_id)
        # air constraints
        prob += adtc_vars[adtc_id] - facility_vars["AirDepot"][adtc_id.split("$")[1]] <= 0, "AIR_{}".format(adtc_id)

    if model_file:
        prob.writeLP(model_file)
    return prob


def create_bclpcc_model(coverage_dict, num_fac, backup_weight, model_file=None, delineator="$",
                            use_serviceable_demand=False):
    """
    Creates a bclpcc coverage model using the provided coverage dictionary
    and parameters. Writes a .lp file that can be solved with Gurobi

    :param coverage_dict: (dictionary) The coverage to use to generate the model
    :param num_fac: (dictionary) The dictionary of number of facilities to use
    :param backup_weight: (float or int) The backup weight to use in the model
    :param model_file: (string) The model file to output
    :param delineator: (string) The character/symbol used to delineate facility and ids
    :param use_serviceable_demand: (bool) Should we use the serviceable demand rather than demand
    :return: (Pulp problem) The generated problem to solve
    """
    if use_serviceable_demand:
        demand_var = "serviceableDemand"
    else:
        demand_var = "demand"
    validate_coverage(coverage_dict, ["coverage"], ["partial"])
    # Check parameters
    if not isinstance(coverage_dict, dict):
        raise TypeError("coverage_dict is not a dictionary")
    if not isinstance(num_fac, dict):
        raise TypeError("num_fac is not a dictionary")
    if not (isinstance(backup_weight, float) or isinstance(backup_weight, int)):
        raise TypeError("backup weight is not float or int")
    if backup_weight > 1.0 or backup_weight < 0.0:
        raise ValueError("Backup weight must be between 0 and 1")
    if model_file and not (isinstance(model_file, str)):
        raise TypeError("model_file is not a string")
    if not isinstance(delineator, str):
        raise TypeError("delineator is not a string")
    primary_weight = 1 - backup_weight
    primary_vars = {}
    backup_vars = {}
    overall_vars = {}
    for demand_id in coverage_dict["demand"]:
        primary_vars[demand_id] = pulp.LpVariable("W{}{}".format(delineator, demand_id), 0, None, pulp.LpContinuous)
        backup_vars[demand_id] = pulp.LpVariable("Y{}{}".format(delineator, demand_id), None, None, pulp.LpContinuous)
        overall_vars[demand_id] = pulp.LpVariable("Z{}{}".format(delineator, demand_id), 0, None, pulp.LpContinuous)
    facility_vars = {}
    for facility_type in coverage_dict["facilities"]:
        facility_vars[facility_type] = {}
        for facility_id in coverage_dict["facilities"][facility_type]:
            facility_vars[facility_type][facility_id] = pulp.LpVariable(
                "{}{}{}".format(facility_type, delineator, facility_id), 0, None, pulp.LpInteger)
    # create the problem
    prob = pulp.LpProblem("BCLPCC", pulp.LpMaximize)
    to_sum = []
    # create objective
    for demand_id in coverage_dict["demand"]:
        to_sum.append(backup_weight * backup_vars[demand_id] + primary_weight * primary_vars[demand_id])
    prob += pulp.lpSum(to_sum)
    # constraints
    for demand_id in coverage_dict["demand"]:
        to_sum = []
        for facility_type in coverage_dict["demand"][demand_id]["coverage"]:
            for facility_id in coverage_dict["demand"][demand_id]["coverage"][facility_type]:
                to_sum.append(coverage_dict["demand"][demand_id]["coverage"][facility_type][facility_id] *
                              facility_vars[facility_type][facility_id])
        prob += pulp.lpSum(to_sum) - 1 * overall_vars[demand_id] >= 0, "D{}".format(demand_id)
        prob += primary_vars[demand_id] <= coverage_dict["demand"][demand_id][demand_var], "primarydemand{}".format(
            demand_id)
        prob += primary_vars[demand_id] - overall_vars <= coverage_dict["demand"][demand_id][
            demand_var], "primaryoverall{}".format(demand_id)
        prob += overall_vars[demand_id] - backup_vars[demand_id] >= coverage_dict["demand"][demand_id][
            demand_var], "overallbackup{}".format(demand_id)
        prob += overall_vars[demand_id] <= 2 * coverage_dict["demand"][demand_id][demand_var], "overalldemand{}".format(
            demand_id)
    # Number of total facilities
    to_sum = []
    for facility_type in coverage_dict["facilities"]:
        for facility_id in coverage_dict["facilities"][facility_type]:
            to_sum.append(facility_vars[facility_type][facility_id])
    prob += pulp.lpSum(to_sum) <= num_fac["total"], "NumTotalFacilities"
    # Number of other facility types
    for facility_type in coverage_dict["facilities"].keys():
        if facility_type in num_fac and facility_type != "total":
            to_sum = []
            for facility_id in coverage_dict["facilities"][facility_type]:
                to_sum.append(facility_vars[facility_type][facility_id])
            prob += pulp.lpSum(to_sum) <= num_fac[facility_type], "Num{}".format(facility_type)
    if model_file:
        prob.writeLP(model_file)
    return prob