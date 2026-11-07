"""
起始调用总条数为7
起始调用客观条数为3
起始调用主观条数为3
预更新：优先调用情绪值相似的记忆，需更改短期记忆保存结构
"""
def happiness_memory(happiness):
    if 80 <= happiness <= 90 :
        all_memory_num = 7 - 1
    elif 90 < happiness <= 100:
        all_memory_num = 7 - 2
    elif 20 <= happiness <= 30:
        all_memory_num = 7 + 1
    elif 10 <= happiness < 20:
        all_memory_num = 7 + 2
    elif 0 <= happiness < 10:
        all_memory_num = 7 + 3
    else:
        all_memory_num = 7
    return all_memory_num
def excited_and_negative_memory(excited,negative_emotion,all_memory_num):
    """激动值和负面值共同影响主客观调用条数
    """
    if 35 <= excited <= 65:
        subjective_memory_num = 3
        objective_memory_num = 3
        if 2 <= negative_emotion < 5:
            subjective_memory_num = subjective_memory_num + 1
            objective_memory_num = all_memory_num - subjective_memory_num
        elif 5 <= negative_emotion < 10:
            subjective_memory_num = subjective_memory_num + 2
            objective_memory_num = all_memory_num - subjective_memory_num

    elif 20 <= excited < 35:
        subjective_memory_num = 2
        objective_memory_num = 4
        if 2 <= negative_emotion < 5:
            objective_memory_num =  objective_memory_num + 1
            subjective_memory_num = all_memory_num - objective_memory_num
        elif 5 <= negative_emotion < 10:
            objective_memory_num = objective_memory_num + 2
            subjective_memory_num = all_memory_num - objective_memory_num


    elif 0 <= excited < 20:
        subjective_memory_num = 1
        objective_memory_num = 5
        if 2 <= negative_emotion < 5:
            objective_memory_num = objective_memory_num + 1
            subjective_memory_num = all_memory_num - objective_memory_num
        elif 5 <= negative_emotion < 10:
            objective_memory_num = objective_memory_num + 2
            subjective_memory_num = all_memory_num - objective_memory_num


    elif 65 < excited <= 80:
        subjective_memory_num = 4
        objective_memory_num = 2
        if 2 <= negative_emotion < 5:
            subjective_memory_num = subjective_memory_num + 1
            objective_memory_num = all_memory_num - subjective_memory_num
        elif 5 <= negative_emotion < 10:
            subjective_memory_num =  subjective_memory_num + 2
            objective_memory_num = all_memory_num - subjective_memory_num

    elif 80 < excited <= 100:
        subjective_memory_num = 5
        objective_memory_num = 1
        if 2 <= negative_emotion < 5:
            subjective_memory_num = subjective_memory_num + 1
            objective_memory_num = all_memory_num - subjective_memory_num
        elif 5 <= negative_emotion < 10:
            subjective_memory_num =  subjective_memory_num + 2
            objective_memory_num = all_memory_num - subjective_memory_num

    if subjective_memory_num > 5:
        subjective_memory_num = 5
    if subjective_memory_num < 0:
        subjective_memory_num = 0
    if objective_memory_num > 5:
        objective_memory_num = 5
    if objective_memory_num < 0:
        objective_memory_num = 0
    #返回主，客观调用数量
    return subjective_memory_num,objective_memory_num