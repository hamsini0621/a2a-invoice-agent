from sys import argv
from jinja2 import Template
import matplotlib.pyplot as plt




flag=argv[1]
identity=argv[2]
error=None
html_out=None

error_temp=Template("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Something Went Wrong</title>
</head>
<body>
    <h1>Wrong Inputs</h1>
    <p>Something Went Wrong</p>
</body>
</html>""")

student_temp=Template("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Student Data</title>
    <style>
        table,th,td{
            border:1px solid black;
            border-collapse: collapse;
        }
    </style>
</head>
<body>
    <h1>Student Data</h1> 
    <table>
        <thead>
            <tr>
                <th>Student id</th>
                <th>Course id</th>
                <th>Marks</th>
            </tr>
        </thead>
        <tbody>
            
            {% for key in data_dic %}
                <tr>
                    <td>{{stud_id}}</td>  
                    <td>{{key}}</td>
                    <td>{{data_dic[key]}}</td>
                    {%set total = total + data_dic[key]%}
                </tr>
            {%endfor%}
        </tbody>
        <tfoot>
            <tr>         
                <td colspan="2">Total Marks
                <td>{{total}}</td>
            </tr>
        </tfoot>

                

   </table>
</body>
</html>
                

   </table>
</body>
</html>""")

course_temp=Template("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Document</title>
    <style>
        table,th,td{
            border:1px solid black;
            border-collapse: collapse;
        }
    </style>
    
</head>
<body>
    <h1>Student Data</h1> 
    <table>
        <thead>
            <tr>
                <td>Average Marks</td>
                <td>Maximum marks</td>
            </tr>
        </thead>
        
        <tfoot>
            <td>{{ average_marks }}</td>
            <td>{{ maximum_marks }}</td>
        </tfoot>        

    </table><br>
    <img src="plot.png", height="250px",width="250px">
                     
</body>
</html>""")

def create_plot(marks):
    plt.hist(marks)
    plt.xlabel('Marks')
    plt.ylabel('Frequency')
    plt.savefig("plot.png", dpi=200)
    #plt.show()





with open('data.csv','r') as f:
    next(f)
    data=f.readlines()

    


if flag!='-s' and flag!='-c':
    error='flag'

elif flag=='-s':
    course_marks={}
    total=0
    for row in data:
        row=row.strip().split(', ')
        s_id=row[0]
        mark=int(row[2])
        if s_id==identity:
            c_id=row[1]
            total+=mark
            course_marks[c_id]=mark
    
    if not course_marks:
        error='Wrong student id'

elif flag=='-c':
    mark_list=[]
    course_marks={}
    for row in data:
        row=row.strip().split(', ')
        c_id=row[1]
        if identity==c_id:
            mark=int(row[2])
            mark_list.append(mark)

    if not mark_list:
        error='Wrong course_id'
    
    else:
        max_mark=max(mark_list)
        average=sum(mark_list)/len(mark_list)
        create_plot(mark_list)


if error:
    print(error)
    html_out=error_temp.render()  
else:
    if flag=='-s':
        html_out=student_temp.render(data_dic=course_marks,stud_id=identity,total=total)
    else:
        html_out=course_temp.render(average_marks=average,maximum_marks=max_mark)


with open("output.html",'w') as w:
    w.write(html_out)
      

        

        