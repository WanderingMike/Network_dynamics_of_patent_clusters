from data_preprocessing import *
from random import shuffle
from functions.functions_ML import *
import sklearn.model_selection
import sklearn.datasets
import sklearn.metrics
import autosklearn.classification
import os
from datetime import datetime
import pickle
from tqdm import tqdm

pd.set_option('display.max_rows', 25)
pd.set_option('display.max_columns', 20)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', 25)
np.set_printoptions(threshold=sys.maxsize)

number_of_cores = 2
search_min = 15
search_hours = 0
ml_search_time = search_min*60 + search_hours*3600


def calculate_emergingness(ml_df, tensor_patent, tensor_cpc_sub_patent, clean_files=False):
    '''Core of the ML part. This function first divides the data into completed data with pre-existing forward citations
    on the chosen time period, and a subset of the dataframe for which we need to find the citation count. We then trust
    blobcity's AutoAI framework to choose the optimal ML framework for us, including the optimal hyperparameters.'''

    # Categorise output to make it a classification problem
    median_forward_citations = ml_df["forward_citations"].median()
    quartile_split = get_statistics(ml_df)
    ml_df["output"] = ml_df["forward_citations"].apply(lambda x: categorise_output(x, quartile_split))

    data_to_forecast = ml_df[ml_df["forward_citations"].isna()]
    X = ml_df[~ml_df["forward_citations"].isna()]

    # Balance the dataset
    X = balance_dataset(X)
    
    # One hot encoding MF
    print(f'2.2.1.1 One hot encoding the datasets ({datetime.now()})')
    X, encoded_columns = onehotencode(X, tensor_cpc_sub_patent)
    data_to_forecast, trash = onehotencode(data_to_forecast, tensor_cpc_sub_patent, columns=encoded_columns)

    print("2.2.1.2 Balanced dataset and dataset to forecast ({})".format(datetime.now()))
    print(X)
    print(data_to_forecast)

    # Splitting dataframe
    print("2.2.1.3 Running ML classifier ({})".format(datetime.now()))
    cls = autosklearn.classification.AutoSklearnClassifier(time_left_for_this_task=ml_search_time,
                                                           resampling_strategy='cv', 
                                                           resampling_strategy_arguments={'folds':5},
                                                           memory_limit=None)

    cls.fit(X.drop(["date", "forward_citations", "output"], axis=1), X["output"])
    print("2.2.1.4 sprint statistics ({})".format(datetime.now()))
    print(cls.sprint_statistics())

    predictions = cls.predict(data_to_forecast.drop(["date", "forward_citations", "output"], axis=1))

    print("2.2.1.5 Predicted outputs ({})".format(datetime.now()))
    print(predictions)

    print("2.2.1.6 Show statistics again, model selection and leaderboard ({})".format(datetime.now()))
    print(cls.sprint_statistics())
    print(cls.show_models())
    print(cls.leaderboard())

    data_to_forecast["output"] = predictions

    ml_df = pd.concat([X, data_to_forecast], axis=0)
    
    print("2.2.1.7 Final dataframe ({})".format(datetime.now()))
    print(ml_df)

    # Add output data to tensor_patent
    for index, row in ml_df.iterrows():
        tensor_patent[index]["output"] = row["output"]

    return ml_df, tensor_patent


def calculate_indicators(ml_df, start, end, tensor_patent, tensor_cpc_sub_patent):
    '''
    This function calculates two indicators and retrieves textual information per CPC group per year:
    - emergingness: the average citation level
    - patent_count: the number of patents at the end of the year
    - keywords: main keywords found in patent abstracts
    - topic: main topics found in patent abstracts
    :param ml_df: data frame used for ML analytics
    :param start: start of time series
    :param end: end of time series
    :param category: CPC group to consider
    :param tensor_patent: contains all patent abstracts
    :return: returns the time-series, complete for one CPC group
    '''


    series = {cpc_subgroup: dict() for cpc_subgroup in tensor_cpc_sub_patent.keys()}
    
    print("2.2.1 Calculating emergingness for entire dataframe ({})".format(datetime.now()))
    df_final, tensor_patent = calculate_emergingness(ml_df, tensor_patent, tensor_cpc_sub_patent)

    print("2.1.3 Saving df with emergingness ({})".format(datetime.now()))
    print(df_final)
    df_final.to_pickle("data/dataframes/df_final.pkl")
#    df_final = pd.read_pickle("data/dataframes/df_final.pkl")
    ffile = open("data/dataframes/dic_tensor_patent", "wb")
    pickle.dump(tensor_patent, ffile)
#    tensor_patent = pickle.load(ffile)

    for cpc_subgroup in tqdm(series.keys()):
        
        series[cpc_subgroup] = {year: None for year in range(start.year, end.year+1)}

        patents_in_subgroup = tensor_cpc_sub_patent[cpc_subgroup]
        subgroup_df = df_final[df_final.index.isin(patents_in_subgroup)]


        for year in range(end.year-10, end.year+1):

            # Filtering patents
            start_date = subgroup_df["date"] >= datetime(year, 1, 1)
            end_date = subgroup_df["date"] <= datetime(year, 12, 31)

            filters = start_date & end_date
            temp_df = subgroup_df[filters]
            patents_per_year = list(temp_df.index.values)

            # Calculating indicators
            patent_count = len(patents_per_year)
            emergingness = temp_df["output"].mean()

            # Adding to time-series
            indicators = {"emergingness": emergingness,
                          "patent_count": patent_count}

            series[cpc_subgroup][year] = indicators

        series[cpc_subgroup]["patents_final_year"] = patents_per_year

    return series, tensor_patent


def run_ML(tensors, period_start, period_end):
    '''Each Worker process will create part of the tensor. This tensor (Python dictionary) will have as keys a subset of
    either patent IDs, assignee IDs, or cpc categories. The values will be populated according to the breadth of content
    in each dataframe tensor_df.
    Format:
        {assignee_A: [patent_1, patent_2,...],
         assignee_B: [...],
         ...}
    '''
    print("2.1 Preparing dataframe ({})".format(datetime.now()))
    ml_df = data_preparation(tensors, period_start, period_end)

    print("2.2 Calculating indicators ({})".format(datetime.now()))
    time_series, tensors["patent"] = calculate_indicators(ml_df,
                                                          period_start,
                                                          period_end,
                                                          tensors["patent"],
                                                          tensors["cpc_sub_patent"])

    return time_series, tensors



